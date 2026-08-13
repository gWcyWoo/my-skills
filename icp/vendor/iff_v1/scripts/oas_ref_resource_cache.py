#!/usr/bin/env python3
"""Discover and deterministically merge transitive Apifox OAS ref resources."""

from __future__ import annotations

import argparse
import json
import posixpath
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote, urldefrag, urljoin, urlsplit, urlunsplit


ROOT = "<root>"
PERCENT_ESCAPE = re.compile(r"%[0-9a-fA-F]{2}")
INVALID_PERCENT = re.compile(r"%(?![0-9a-fA-F]{2})")
URI_PATH_SAFE = "/%:@!$&'()*+,;=-._~"


class CacheError(ValueError):
    """The ref-resource cache cannot progress deterministically."""


def load_json_value(path: Path, label: str) -> object:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, str):
            value = json.loads(value)
        return value
    except (OSError, json.JSONDecodeError) as exc:
        raise CacheError(f"invalid {label} JSON at {path}: {exc}") from exc


def parse_resource_document(value: object, key: str) -> object:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise CacheError(f"invalid ref resource JSON: {key}: {exc}") from exc
    if not isinstance(value, (dict, list)):
        raise CacheError(f"ref resource must be a JSON object or array: {key}")
    return value


def canonical_uri_path(path: str) -> str:
    if INVALID_PERCENT.search(path):
        raise CacheError(f"invalid percent encoding in ref resource path: {path}")
    encoded = quote(path, safe=URI_PATH_SAFE)
    return PERCENT_ESCAPE.sub(lambda match: match.group(0).upper(), encoded)


def canonical_document_key(document_ref: str, current_document: str = ROOT) -> str:
    parsed = urlsplit(document_ref)
    if parsed.scheme:
        normalized_path = posixpath.normpath(parsed.path)
        if parsed.path.startswith("/") and not normalized_path.startswith("/"):
            normalized_path = "/" + normalized_path
        return urlunsplit(
            (
                parsed.scheme.lower(),
                parsed.netloc,
                canonical_uri_path(normalized_path),
                parsed.query,
                "",
            )
        )

    if current_document != ROOT and urlsplit(current_document).scheme:
        return canonical_document_key(urljoin(current_document, document_ref), ROOT)

    if parsed.path.startswith("/"):
        normalized_path = posixpath.normpath(parsed.path)
    else:
        base = "/" if current_document == ROOT else posixpath.dirname(current_document)
        normalized_path = posixpath.normpath(posixpath.join(base, parsed.path))
    if not normalized_path.startswith("/"):
        normalized_path = "/" + normalized_path
    canonical_path = canonical_uri_path(normalized_path)
    return urlunsplit(("", "", canonical_path, parsed.query, ""))


def load_resource_map(path: Path, label: str) -> dict[str, object]:
    value = load_json_value(path, label)
    if not isinstance(value, dict):
        raise CacheError(f"{label} must be a JSON object mapping refs to documents")
    normalized: dict[str, object] = {}
    for raw_key, document in value.items():
        if not isinstance(raw_key, str):
            raise CacheError(f"{label} keys must be strings")
        document_ref, fragment = urldefrag(raw_key)
        if fragment:
            raise CacheError(f"ref resource key must not contain a fragment: {raw_key}")
        key = canonical_document_key(document_ref)
        parsed_document = parse_resource_document(document, raw_key)
        if key in normalized and normalized[key] != parsed_document:
            raise CacheError(f"conflicting duplicate ref resource: {key}")
        normalized[key] = parsed_document
    return normalized


def collect_external_refs(value: object, current_document: str, found: set[str]) -> None:
    if isinstance(value, list):
        for item in value:
            collect_external_refs(item, current_document, found)
        return
    if not isinstance(value, dict):
        return
    if "$ref" in value:
        ref = value["$ref"]
        if not isinstance(ref, str) or not ref:
            raise CacheError("$ref must be a non-empty string")
        document_ref, _fragment = urldefrag(ref)
        if document_ref:
            found.add(canonical_document_key(document_ref, current_document))
    for item in value.values():
        collect_external_refs(item, current_document, found)


def write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            temp_path = Path(handle.name)
        temp_path.replace(path)
    except OSError as exc:
        raise CacheError(f"cannot write {path}: {exc}") from exc
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def command_missing(args: argparse.Namespace) -> int:
    oas = load_json_value(Path(args.oas), "OAS root")
    if not isinstance(oas, dict):
        raise CacheError("OAS root must be a JSON object")
    resources = load_resource_map(Path(args.ref_resources), "OAS ref resources")
    found: set[str] = set()
    collect_external_refs(oas, ROOT, found)
    for key, document in resources.items():
        collect_external_refs(document, key, found)
    missing = sorted(found - set(resources))
    write_json_atomic(Path(args.out), missing)
    print(f"ok missing_oas_ref_resources count={len(missing)} -> {args.out}")
    return 0


def command_merge(args: argparse.Namespace) -> int:
    base = load_resource_map(Path(args.base), "base OAS ref resources")
    incoming = load_resource_map(Path(args.incoming), "incoming OAS ref resources")
    required_value = load_json_value(Path(args.required), "required OAS ref paths")
    if not isinstance(required_value, list) or not all(
        isinstance(item, str) for item in required_value
    ):
        raise CacheError("required OAS ref paths must be a JSON string array")
    required = {canonical_document_key(item) for item in required_value}
    if not required:
        raise CacheError("required OAS ref paths must not be empty")

    already_cached = sorted(required & set(base))
    if already_cached:
        raise CacheError(f"repeated missing refs already cached: {already_cached}")
    new_keys = set(incoming) - set(base)
    if not new_keys:
        raise CacheError("no progress: incoming response added no resources")
    not_returned = sorted(required - set(incoming))
    if not_returned:
        raise CacheError(f"required ref resources not returned: {not_returned}")
    conflicts = sorted(
        key for key in set(base) & set(incoming) if base[key] != incoming[key]
    )
    if conflicts:
        raise CacheError(f"incoming response conflicts with cached resources: {conflicts}")

    merged = {key: (incoming[key] if key in incoming else base[key]) for key in sorted(set(base) | set(incoming))}
    write_json_atomic(Path(args.out), merged)
    print(f"ok merge_oas_ref_resources added={len(new_keys)} total={len(merged)} -> {args.out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    missing = subparsers.add_parser("missing")
    missing.add_argument("--oas", required=True)
    missing.add_argument("--ref-resources", required=True)
    missing.add_argument("--out", required=True)
    missing.set_defaults(handler=command_missing)

    merge = subparsers.add_parser("merge")
    merge.add_argument("--base", required=True)
    merge.add_argument("--incoming", required=True)
    merge.add_argument("--required", required=True)
    merge.add_argument("--out", required=True)
    merge.set_defaults(handler=command_merge)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.handler(args)
    except CacheError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
