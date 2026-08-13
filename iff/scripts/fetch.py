#!/usr/bin/env python3
"""
fetch.py — Resolve a Lanhu UI design URL and persist its raw Figma JSON to disk.

Pipeline (mirrors Lanhu's web UI click-to-inspect data path):
    URL --(parse image_id, pid, tid)--> /api/project/image
       --(latest_version.json_url)--> CDN FigmaJSON*.json (gzip)
       --(wrap with design_name/id/url)--> {parent_dir}/{sanitized_name}/raw.json

Usage:
    python3 fetch.py --url "<lanhu URL with image_id>" --parent-dir <dir>
        # writes <parent>/<sanitized_name>/raw.json
        # stdout: one line JSON {raw_json, dir, design_name, design_id, lanhu_url}

    python3 fetch.py --url "<...>" --output <full path to raw.json>
        # writes exactly that path; stdout same shape

The bulk JSON is NEVER printed to stdout — that prevents callers (especially
LLM orchestrators) from accidentally pulling 100s of KB into their context.

Cookie resolution order:
    1. --cookie <value>
    2. $LANHU_COOKIE
    3. ~/.codex/mcp/lanhu-mcp/.env  (LANHU_COOKIE="...")
    4. ~/.claude/mcp/lanhu-mcp/.env  (legacy fallback)
"""

import argparse
import gzip
import json
import os
import sys
import urllib.parse
import urllib.request


def read_cookie_from_dotenv(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("LANHU_COOKIE="):
                continue
            v = line.split("=", 1)[1].strip()
            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                v = v[1:-1]
            return v
    return None


def resolve_cookie(cli_cookie):
    if cli_cookie:
        return cli_cookie
    env_v = os.environ.get("LANHU_COOKIE", "").strip()
    if env_v:
        return env_v
    for dotenv in (
        os.path.expanduser("~/.codex/mcp/lanhu-mcp/.env"),
        os.path.expanduser("~/.claude/mcp/lanhu-mcp/.env"),
    ):
        cookie = read_cookie_from_dotenv(dotenv)
        if cookie:
            return cookie
    return None


def parse_lanhu_url(url):
    """Extract image_id / pid / tid from a Lanhu hash-routed URL."""
    parsed = urllib.parse.urlparse(url)
    fragment = parsed.fragment or ""
    if "?" in fragment:
        qs = fragment.split("?", 1)[1]
    else:
        qs = parsed.query or ""
    params = dict(urllib.parse.parse_qsl(qs))
    return {
        "image_id": params.get("image_id"),
        "project_id": params.get("pid") or params.get("project_id"),
        "team_id": params.get("tid") or params.get("team_id"),
        "raw_params": params,
    }


def http_get(url, cookie, referer="https://lanhuapp.com/", timeout=30):
    req = urllib.request.Request(
        url,
        headers={
            "Cookie": cookie,
            "Referer": referer,
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        ce = (resp.headers.get("Content-Encoding") or "").lower()
        if ce == "gzip" or data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        return data


def fetch_image_meta(cookie, image_id, project_id, team_id):
    """Call /api/project/image to get design name and latest version's json_url."""
    api = (
        f"https://lanhuapp.com/api/project/image"
        f"?dds_status=1&image_id={image_id}"
        f"&team_id={team_id}&project_id={project_id}"
    )
    body = http_get(api, cookie)
    data = json.loads(body)
    if data.get("code") != "00000":
        raise RuntimeError(f"project/image failed: code={data.get('code')} msg={data.get('msg')}")
    result = data.get("result") or {}
    versions = result.get("versions") or []
    if not versions:
        raise RuntimeError("project/image returned no versions")
    latest = versions[0]
    json_url = latest.get("json_url")
    if not json_url:
        raise RuntimeError("latest version has no json_url")
    return {
        "design_id": result.get("id"),
        "design_name": result.get("name") or "untitled",
        "version_id": latest.get("id"),
        "json_url": json_url,
    }


_UNSAFE_FS = ("/", "\\", ":", "\0")


def sanitize_name(name):
    """Replace filesystem-unsafe characters with '-'. Preserve everything else
    verbatim (including Chinese characters, full-width punctuation, and spaces)."""
    out = name or "untitled"
    for ch in _UNSAFE_FS:
        out = out.replace(ch, "-")
    return out.strip() or "untitled"


_FIGMA_SLICE_PREFIX_PNG = "FigmaSlicePNG"
_FIGMA_SLICE_PREFIX_SVG = "FigmaSliceSVG"


def slice_filename(url):
    """Extract a stable, filesystem-safe filename from a Lanhu slice URL.

    https://.../FigmaSlicePNGabc123.png  ->  abc123.png
    https://.../FigmaSliceSVGdef456.svg  ->  def456.svg
    Falls back to the basename when the prefix is missing.
    """
    base = url.rsplit("/", 1)[-1].split("?", 1)[0]
    for prefix in (_FIGMA_SLICE_PREFIX_PNG, _FIGMA_SLICE_PREFIX_SVG):
        if base.startswith(prefix):
            return base[len(prefix):]
    return base


def collect_slice_layers(figma_json):
    """Walk artboard.layers; yield every layer with hasExportImage=true and a
    downloadable image URL. Mirrors lanhu-mcp's logic.
    """
    artboard = figma_json.get("artboard") or {}

    def walk(node, parent_path=""):
        if not isinstance(node, dict):
            return
        name = node.get("name", "")
        path = f"{parent_path}/{name}" if parent_path else name
        img = node.get("image") or {}
        url = img.get("imageUrl") or img.get("svgUrl")
        if url and node.get("hasExportImage"):
            yield {
                "id": node.get("id"),
                "name": name,
                "layer_path": path,
                "frame": node.get("frame") or {},
                "png_url": img.get("imageUrl"),
                "svg_url": img.get("svgUrl"),
            }
        for sub in node.get("layers") or []:
            yield from walk(sub, path)

    yield from walk(artboard)


def download_slices(figma_json, target_dir, cookie):
    """Download every exportable slice into <target_dir>/assets/.
    Dedup by URL — multiple layers can reference the same file.
    Returns a list of {layer_id, layer_path, png_path, svg_path}.
    """
    assets_dir = os.path.join(target_dir, "assets")
    os.makedirs(assets_dir, exist_ok=True)

    url_to_local = {}
    manifest = []

    for layer in collect_slice_layers(figma_json):
        entry = {
            "layer_id": layer["id"],
            "layer_name": layer["name"],
            "layer_path": layer["layer_path"],
            "frame": layer["frame"],
            "png_url": layer["png_url"],
            "svg_url": layer["svg_url"],
            "png_path": None,
            "svg_path": None,
        }
        for url, fmt_key in ((layer["png_url"], "png_path"), (layer["svg_url"], "svg_path")):
            if not url:
                continue
            if url in url_to_local:
                entry[fmt_key] = url_to_local[url]
                continue
            fname = slice_filename(url)
            local_path = os.path.join(assets_dir, fname)
            try:
                body = http_get(url, cookie, referer="https://lanhuapp.com/")
                with open(local_path, "wb") as f:
                    f.write(body)
                rel = os.path.join("assets", fname)
                url_to_local[url] = rel
                entry[fmt_key] = rel
            except Exception as e:
                print(f"WARN: slice download failed {url}: {e}", file=sys.stderr)
        manifest.append(entry)
    return manifest


def resolve_target_path(parent_dir, design_name, design_id):
    """Pick <parent>/<sanitized_name>/raw.json, suffixing _2/_3/... if a
    different design already lives in that directory."""
    safe = sanitize_name(design_name)
    base = os.path.join(parent_dir, safe)
    candidate = base
    i = 1
    while True:
        raw = os.path.join(candidate, "raw.json")
        if not os.path.isdir(candidate):
            return candidate, raw
        # Directory exists. If raw.json belongs to the same design_id, treat as
        # re-run and overwrite. Otherwise pick a new suffix.
        if os.path.exists(raw):
            try:
                with open(raw, encoding="utf-8") as f:
                    existing = json.load(f)
                if existing.get("design_id") == design_id:
                    return candidate, raw
            except Exception:
                pass
        i += 1
        candidate = f"{base}_{i}"


def main():
    ap = argparse.ArgumentParser(description="Resolve a Lanhu UI design URL into raw Figma JSON on disk.")
    ap.add_argument("--url", required=True, help="Lanhu URL containing image_id")
    ap.add_argument("--cookie", default=None, help="Override cookie (else env / dotenv)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--parent-dir", help="Parent dir; raw.json goes into <parent>/<sanitized_name>/raw.json")
    g.add_argument("--output", help="Exact path to write raw.json (no name sanitization, no collision handling)")
    args = ap.parse_args()

    cookie = resolve_cookie(args.cookie)
    if not cookie:
        print(
            "ERROR: cookie not found. Set $LANHU_COOKIE or write LANHU_COOKIE=... "
            "into ~/.codex/mcp/lanhu-mcp/.env "
            "(legacy ~/.claude/mcp/lanhu-mcp/.env is also supported)",
            file=sys.stderr,
        )
        sys.exit(1)

    parsed = parse_lanhu_url(args.url)
    if not parsed["image_id"]:
        print("ERROR: URL is missing image_id parameter", file=sys.stderr)
        sys.exit(2)
    if not parsed["project_id"]:
        print("ERROR: URL is missing pid (project_id)", file=sys.stderr)
        sys.exit(2)

    team_id = parsed["team_id"] or ""

    try:
        meta = fetch_image_meta(cookie, parsed["image_id"], parsed["project_id"], team_id)
    except Exception as e:
        print(f"ERROR: project/image lookup failed: {e}", file=sys.stderr)
        sys.exit(3)

    try:
        body = http_get(meta["json_url"], cookie)
        figma_json = json.loads(body)
    except Exception as e:
        print(f"ERROR: fetch raw Figma JSON failed: {e}", file=sys.stderr)
        sys.exit(4)

    wrapper = {
        "design_name": meta["design_name"],
        "design_id": meta["design_id"],
        "version_id": meta["version_id"],
        "lanhu_url": args.url,
        "figma_json": figma_json,
    }

    if args.output:
        target_dir = os.path.dirname(os.path.abspath(args.output)) or "."
        raw_path = os.path.abspath(args.output)
    else:
        target_dir, raw_path = resolve_target_path(
            os.path.abspath(args.parent_dir), meta["design_name"], meta["design_id"]
        )

    try:
        os.makedirs(target_dir, exist_ok=True)
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(wrapper, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"ERROR: failed to write raw.json: {e}", file=sys.stderr)
        sys.exit(5)

    slices_manifest = download_slices(figma_json, target_dir, cookie)
    if slices_manifest:
        manifest_path = os.path.join(target_dir, "assets", "manifest.json")
        try:
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(slices_manifest, f, ensure_ascii=False, indent=2)
        except OSError as e:
            print(f"WARN: manifest write failed: {e}", file=sys.stderr)
        downloaded = sum(1 for s in slices_manifest if s["png_path"] or s["svg_path"])
        print(f"[fetch.py] slices: {downloaded}/{len(slices_manifest)} downloaded", file=sys.stderr)

    summary = {
        "raw_json": raw_path,
        "dir": target_dir,
        "design_name": meta["design_name"],
        "design_id": meta["design_id"],
        "version_id": meta["version_id"],
        "lanhu_url": args.url,
        "slices_count": len(slices_manifest),
    }
    json.dump(summary, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
