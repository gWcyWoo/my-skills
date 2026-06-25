#!/usr/bin/env python3
"""Download the complete Lanhu cover image for an artboard."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from fetch import fetch_image_meta, http_get, parse_lanhu_url, resolve_cookie
from common import png_size


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--cookie", default=None)
    args = parser.parse_args()

    cookie = resolve_cookie(args.cookie)
    if not cookie:
        print("ERROR: cookie not found. Set LANHU_COOKIE or pass --cookie.", file=sys.stderr)
        return 2

    parsed = parse_lanhu_url(args.url)
    image_id = parsed.get("image_id")
    project_id = parsed.get("project_id")
    team_id = parsed.get("team_id") or "0"
    if not image_id or not project_id:
        print("ERROR: Lanhu URL missing image_id/project_id.", file=sys.stderr)
        return 2

    meta = fetch_image_meta(cookie, image_id, project_id, team_id)
    api = (
        "https://lanhuapp.com/api/project/image"
        f"?dds_status=1&image_id={image_id}&team_id={team_id}&project_id={project_id}"
    )
    data = json.loads(http_get(api, cookie))
    result = data.get("result") or {}
    versions = result.get("versions") or []
    cover_url = result.get("url") or (versions[0].get("url") if versions else None)
    if not cover_url:
        print("ERROR: /api/project/image returned no result.url or versions[0].url.", file=sys.stderr)
        return 1

    body = http_get(cover_url, cookie)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body)
    width, height = png_size(out)
    manifest = out.with_name("visual_manifest.json")
    manifest.write_text(
        json.dumps(
            {
                "reference_source": "Lanhu /api/project/image result.url or versions[0].url",
                "reference_url": cover_url,
                "reference_size": {"width": width, "height": height},
                "design_id": meta.get("design_id"),
                "version_id": meta.get("version_id"),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
