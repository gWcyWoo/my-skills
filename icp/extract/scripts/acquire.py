#!/usr/bin/env python3
"""Acquire one complete Lanhu design without depending on another skill."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from lanhu import (
    HttpClient,
    LanhuError,
    artboard_size,
    asset_file_name,
    collect_export_assets,
    fetch_design_metadata,
    json_bytes,
    parse_lanhu_url,
    png_size,
    reference_logical_scale,
    resolve_cookie,
    sha256_bytes,
)


def acquire(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir).resolve()
    if output_dir.exists():
        raise LanhuError("output_exists", f"acquisition output already exists: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    cookie = resolve_cookie(args.cookie)
    if not cookie:
        raise LanhuError(
            "missing_cookie",
            "set LANHU_COOKIE or configure ~/.agents/mcp/lanhu-mcp/.env",
        )
    identity = parse_lanhu_url(args.url)
    fixture = Path(args.http_fixture).resolve() if args.http_fixture else None
    client = HttpClient(cookie, fixture)
    metadata = fetch_design_metadata(client, identity, args.api_base)
    try:
        figma_json = json.loads(client.get(metadata["json_url"]))
    except json.JSONDecodeError as exc:
        raise LanhuError("invalid_figma_json", str(exc)) from exc
    if not isinstance(figma_json, dict):
        raise LanhuError("invalid_figma_json", "Figma JSON root must be an object")
    reference_raw = client.get(metadata["cover_url"])
    reference_size = png_size(reference_raw)
    source_artboard_size = artboard_size(figma_json)
    logical_scale = reference_logical_scale(reference_size, source_artboard_size)

    expected_assets = collect_export_assets(figma_json)
    unique_assets: dict[str, list[dict[str, Any]]] = {}
    for expected in expected_assets:
        unique_assets.setdefault(expected["url"], []).append(expected)
    wrapper = {
        "design_name": metadata["design_name"],
        "design_id": metadata["design_id"],
        "version_id": metadata["version_id"],
        "lanhu_url": args.url,
        "source_identity": identity,
        "figma_json": figma_json,
    }
    source_raw = json_bytes(wrapper)

    with tempfile.TemporaryDirectory(prefix=".acquire-", dir=output_dir.parent) as temp_name:
        temp_dir = Path(temp_name)
        assets_dir = temp_dir / "assets"
        assets_dir.mkdir()
        used_names: dict[str, str] = {}
        asset_files: list[dict[str, Any]] = []
        for url in sorted(unique_assets):
            try:
                body = client.get(url)
            except LanhuError as exc:
                raise LanhuError(
                    "asset_download_failed", f"expected asset {url} failed: {exc.message}"
                ) from exc
            if not body:
                raise LanhuError("asset_download_failed", f"expected asset {url} is empty")
            file_name = asset_file_name(url, used_names)
            relative_path = Path("assets") / file_name
            (temp_dir / relative_path).write_bytes(body)
            asset_files.append(
                {
                    "path": relative_path.as_posix(),
                    "url": url,
                    "sha256": sha256_bytes(body),
                    "size": len(body),
                    "references": unique_assets[url],
                }
            )
        expected_count = len(unique_assets)
        downloaded_count = len(asset_files)
        hashed_count = sum(1 for item in asset_files if item["sha256"])
        if expected_count != downloaded_count or downloaded_count != hashed_count:
            raise LanhuError(
                "asset_set_incomplete",
                f"expected={expected_count} downloaded={downloaded_count} hashed={hashed_count}",
            )
        (temp_dir / "design.json").write_bytes(source_raw)
        (temp_dir / "reference.png").write_bytes(reference_raw)
        acquisition = {
            "schema": "icp.extract.lanhu-acquisition.v1",
            "design_url": args.url,
            "identity": {
                **identity,
                "design_id": metadata["design_id"],
                "version_id": metadata["version_id"],
            },
            "design_name": metadata["design_name"],
            "metadata_url": metadata["metadata_url"],
            "json_url": metadata["json_url"],
            "cover_url": metadata["cover_url"],
            "source": {
                "path": "design.json",
                "sha256": sha256_bytes(source_raw),
                "size": len(source_raw),
            },
            "reference": {
                "path": "reference.png",
                "sha256": sha256_bytes(reference_raw),
                "size": reference_size,
                "logical_scale": logical_scale,
                "byte_size": len(reference_raw),
            },
            "artboard_size": source_artboard_size,
            "assets": {
                "expected_count": expected_count,
                "downloaded_count": downloaded_count,
                "hashed_count": hashed_count,
                "complete": True,
                "files": asset_files,
            },
        }
        (temp_dir / "acquisition.json").write_bytes(json_bytes(acquisition))
        os.replace(temp_dir, output_dir)

    return {
        "ok": True,
        "output_dir": str(output_dir),
        "design_name": metadata["design_name"],
        "design_id": metadata["design_id"],
        "version_id": metadata["version_id"],
        "image_id": identity["image_id"],
        "expected_asset_count": expected_count,
        "downloaded_asset_count": downloaded_count,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--cookie")
    parser.add_argument("--api-base", default="https://lanhuapp.com")
    parser.add_argument("--http-fixture", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = acquire(args)
    except LanhuError as exc:
        print(
            json.dumps({"ok": False, "error": exc.code, "message": exc.message}),
            file=sys.stderr,
        )
        return 2
    except OSError as exc:
        print(json.dumps({"ok": False, "error": "io_error", "message": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
