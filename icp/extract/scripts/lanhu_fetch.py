#!/usr/bin/env python3
"""ICP Stage 1 取数 — 把一个蓝湖设计稿 URL 解析成 INPUT.md 契约要求的四件套。

    python3 lanhu_fetch.py --url "<含 image_id 的蓝湖 URL>" --out-dir <dir>

产出 <out-dir>/:
    design.json   顶层含 artboard，直接喂 bind.py --design-json
    slices.json   {"slices":[...]}，直接喂 bind.py --slices-json
    cover.png     整页截图，直接喂 bind.py --cover-image
    assets/       设计师导出的真实切图(png+svg)，按内容哈希命名

走的是蓝湖的静态版本数据，不经 DDS 服务端渲染(store_schema_revise)，
也不经 lanhu MCP —— 切图就在 figma_json 里(hasExportImage + image.imageUrl)。

一次 /api/project/image 调用同时拿到 json_url 与 cover url。

体积大的 JSON 一律不进 stdout，避免灌爆调用方(尤其是模型)的上下文；
stdout 只有一行 summary JSON。

Cookie 解析顺序: --cookie → $LANHU_COOKIE → ~/.codex/mcp/lanhu-mcp/.env
"""

import argparse
import gzip
import json
import os
import struct
import sys
import urllib.parse
import urllib.request
from pathlib import Path


API_BASE = "https://lanhuapp.com/api/project/image"
REFERER = "https://lanhuapp.com/"

_SLICE_PREFIXES = ("FigmaSlicePNG", "FigmaSliceSVG")

# 倍率 → 相对逻辑尺寸的系数。None 表示直接用原图 URL(蓝湖存的就是 4x)。
_SCALES = {
    "1x": 1, "2x": 2, "3x": 3,
    "ios_1x": 1, "ios_2x": 2, "ios_3x": 3,
    "android_mdpi": 1, "android_hdpi": 1.5, "android_xhdpi": 2,
    "android_xxhdpi": 3, "android_xxxhdpi": None,
}


def emit_error(err_type, detail, code=1):
    json.dump({"ok": False, "errors": [{"type": err_type, "detail": detail}]},
              sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return code


# ---------------------------------------------------------------- cookie

def _cookie_from_dotenv(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("LANHU_COOKIE="):
                continue
            v = line.split("=", 1)[1].strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            return v
    return None


def resolve_cookie(cli_cookie):
    if cli_cookie:
        return cli_cookie
    env_v = os.environ.get("LANHU_COOKIE", "").strip()
    if env_v:
        return env_v
    return _cookie_from_dotenv(
        os.path.expanduser("~/.codex/mcp/lanhu-mcp/.env"))


# ---------------------------------------------------------------- HTTP

def parse_lanhu_url(url):
    """蓝湖是 hash 路由，参数在 fragment 里。tid 缺失不影响 —— cookie 已确定团队。"""
    parsed = urllib.parse.urlparse(url)
    fragment = parsed.fragment or ""
    qs = fragment.split("?", 1)[1] if "?" in fragment else (parsed.query or "")
    params = dict(urllib.parse.parse_qsl(qs))
    return {
        "image_id": params.get("image_id"),
        "project_id": params.get("pid") or params.get("project_id"),
        "team_id": params.get("tid") or params.get("team_id") or "",
    }


def http_get(url, cookie, timeout=30):
    req = urllib.request.Request(url, headers={
        "Cookie": cookie,
        "Referer": REFERER,
        "User-Agent": "Mozilla/5.0",
        "Accept-Encoding": "gzip",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        ce = (resp.headers.get("Content-Encoding") or "").lower()
        if ce == "gzip" or data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        return data


def fetch_image_meta(cookie, image_id, project_id, team_id):
    """一次调用取回设计稿名、版本 json_url、cover url。"""
    api = (f"{API_BASE}?dds_status=1&image_id={image_id}"
           f"&team_id={team_id}&project_id={project_id}")
    data = json.loads(http_get(api, cookie))
    if data.get("code") != "00000":
        raise RuntimeError(f"code={data.get('code')} msg={data.get('msg')}")
    result = data.get("result") or {}
    versions = result.get("versions") or []
    if not versions:
        raise RuntimeError("result.versions 为空")
    latest = versions[0]
    if not latest.get("json_url"):
        raise RuntimeError("versions[0] 没有 json_url")
    return {
        "design_id": result.get("id"),
        "design_name": result.get("name") or "untitled",
        "version_id": latest.get("id"),
        "json_url": latest["json_url"],
        "cover_url": result.get("url") or latest.get("url"),
    }


# ---------------------------------------------------------------- 切图

def slice_filename(url):
    """FigmaSlicePNGabc.png → abc.png；缺前缀时退回 basename。"""
    base = url.rsplit("/", 1)[-1].split("?", 1)[0]
    for prefix in _SLICE_PREFIXES:
        if base.startswith(prefix):
            return base[len(prefix):]
    return base


def build_scale_urls(png_url, width, height):
    """按 OSS resize 参数拼多倍率 URL。蓝湖原图存的是 sliceScale 倍，
    xxxhdpi 直接给原图(无参数)。"""
    if not png_url or not width or not height:
        return None
    out = {}
    for key, factor in _SCALES.items():
        if factor is None:
            out[key] = png_url
        else:
            w, h = round(width * factor), round(height * factor)
            out[key] = f"{png_url}?x-oss-process=image/resize,w_{w},h_{h}/format,png"
    return out


def collect_slices(artboard):
    """遍历 artboard.layers，凡 hasExportImage 且有图 URL 的节点即切图。"""
    def walk(node, parent_path=""):
        if not isinstance(node, dict):
            return
        name = node.get("name", "")
        path = f"{parent_path}/{name}" if parent_path else name
        img = node.get("image") or {}
        png_url, svg_url = img.get("imageUrl"), img.get("svgUrl")
        if node.get("hasExportImage") and (png_url or svg_url):
            frame = node.get("frame") or {}
            w, h = frame.get("width"), frame.get("height")
            yield {
                "id": node.get("id"),
                "name": name,
                "layer_path": path,
                "frame": frame,
                "position": {"x": frame.get("left"), "y": frame.get("top")},
                "logical_size": {"width": w, "height": h},
                "download_url": png_url,
                "svg_url": svg_url,
                "scale_urls": build_scale_urls(png_url, w, h),
                "local_png": None,
                "local_svg": None,
            }
        for sub in node.get("layers") or []:
            yield from walk(sub, path)

    yield from walk(artboard)


def download_slices(artboard, out_dir, cookie, warnings):
    """下载到 <out_dir>/assets/，按 URL 去重(多个图层可能引用同一文件)。"""
    assets_dir = out_dir / "assets"
    url_to_local = {}
    slices = list(collect_slices(artboard))
    if slices:
        assets_dir.mkdir(parents=True, exist_ok=True)

    for sl in slices:
        for url, key in ((sl["download_url"], "local_png"), (sl["svg_url"], "local_svg")):
            if not url:
                continue
            if url in url_to_local:
                sl[key] = url_to_local[url]
                continue
            fname = slice_filename(url)
            try:
                (assets_dir / fname).write_bytes(http_get(url, cookie))
            except Exception as e:
                warnings.append(f"切图下载失败 {sl['id']} {fname}: {e}")
                continue
            rel = f"assets/{fname}"
            url_to_local[url] = rel
            sl[key] = rel
    return slices


# ---------------------------------------------------------------- cover

def png_size(path):
    data = Path(path).read_bytes()
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"不是 PNG: {path}")
    return struct.unpack(">II", data[16:24])


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(
        description="蓝湖设计稿 URL → icp Stage 1 契约四件套")
    ap.add_argument("--url", required=True, help="含 image_id 的蓝湖 URL")
    ap.add_argument("--out-dir", required=True, help="产物目录")
    ap.add_argument("--cookie", default=None, help="覆盖 cookie(否则走 env/dotenv)")
    ap.add_argument("--skip-cover", action="store_true",
                    help="不下载整页截图(crop 步骤将无输入)")
    args = ap.parse_args()

    cookie = resolve_cookie(args.cookie)
    if not cookie:
        return emit_error("no_cookie",
                          "设置 $LANHU_COOKIE，或在 ~/.codex/mcp/lanhu-mcp/.env "
                          "写 LANHU_COOKIE=...")

    parsed = parse_lanhu_url(args.url)
    for field in ("image_id", "project_id"):
        if not parsed[field]:
            return emit_error("bad_url", f"URL 缺少 {field}(pid/image_id)", 2)

    try:
        meta = fetch_image_meta(cookie, parsed["image_id"],
                                parsed["project_id"], parsed["team_id"])
    except Exception as e:
        return emit_error("image_meta_failed", f"/api/project/image 失败: {e}", 3)

    try:
        figma_json = json.loads(http_get(meta["json_url"], cookie))
    except Exception as e:
        return emit_error("design_json_failed", f"下载版本 JSON 失败: {e}", 4)

    artboard = figma_json.get("artboard") or {}
    node_count = _count_nodes(artboard)
    # 静默空跑是最坏的失败方式 —— 宁可在这里炸掉。
    if node_count <= 1:
        return emit_error(
            "empty_artboard",
            f"artboard 只有 {node_count} 个节点，版本数据异常，"
            f"后续 bind 会静默绑定 0 节点。json_url={meta['json_url']}", 5)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    warnings = []

    # design.json 顶层就是 figma_json —— bind.py 各命令自己取 .artboard
    (out_dir / "design.json").write_text(
        json.dumps(figma_json, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    slices = download_slices(artboard, out_dir, cookie, warnings)
    (out_dir / "slices.json").write_text(
        json.dumps({"slices": slices}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")

    cover = None
    if not args.skip_cover:
        if not meta["cover_url"]:
            warnings.append("接口未返回 cover url，crop 步骤将无输入")
        else:
            try:
                cover_path = out_dir / "cover.png"
                cover_path.write_bytes(http_get(meta["cover_url"], cookie))
                w, h = png_size(cover_path)
                cover = {"path": str(cover_path), "width": w, "height": h,
                         "source_url": meta["cover_url"]}
            except Exception as e:
                warnings.append(f"cover 下载失败: {e}")

    downloaded = sum(1 for s in slices if s["local_png"] or s["local_svg"])
    summary = {
        "ok": True,
        "dir": str(out_dir),
        "design_json": str(out_dir / "design.json"),
        "slices_json": str(out_dir / "slices.json"),
        "cover_image": cover["path"] if cover else None,
        "design_name": meta["design_name"],
        "design_id": meta["design_id"],
        "version_id": meta["version_id"],
        "node_count": node_count,
        "artboard_frame": artboard.get("frame"),
        "slice_scale": (figma_json.get("meta") or {}).get("sliceScale"),
        "slices_total": len(slices),
        "slices_downloaded": downloaded,
        "cover": cover,
    }
    if warnings:
        summary["warnings"] = warnings
    json.dump(summary, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


def _count_nodes(node):
    if not isinstance(node, dict):
        return 0
    return 1 + sum(_count_nodes(c) for c in (node.get("layers") or []))


if __name__ == "__main__":
    sys.exit(main())
