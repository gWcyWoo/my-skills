#!/usr/bin/env python3
"""自建设计平台适配器 — 把一条设计图链接解析成 INPUT.md 契约要求的四件套。

引用格式: <平台地址>/?project=<项目 id>&design=<设计图 id>，即平台里打开设计图时地址栏的链接。

Cookie 解析顺序: --cookie → $SELFHOST_COOKIE → ~/.config/icp/selfhost.env 里的 SELFHOST_COOKIE=…
"""

import gzip
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

COOKIE_ENV = "SELFHOST_COOKIE"
COOKIE_FILE = "~/.config/icp/selfhost.env"
COOKIE_HINT = (f"把浏览器登录平台后 /api/projects 请求头里的 Cookie 写进 {COOKIE_FILE}"
               f"(一行 {COOKIE_ENV}=…)，或设 ${COOKIE_ENV} / 传 --cookie")
FIGMA_PREFIX = "Figma · "
SLICE_NAME = re.compile(r"^(?P<base>.*) · [A-Z]+ @(?P<scale>\d+(?:\.\d+)?)x(?: \d+)?$")

# 平台(Figma)图层类型 → 蓝湖类型。bind.py / blueprint.py 按蓝湖类型识别文字与组件实例。
LAYER_TYPES = {
    "TEXT": "textLayer",
    "INSTANCE": "symbolInstence",  # 蓝湖原拼写
    "FRAME": "groupLayer", "GROUP": "groupLayer", "SECTION": "groupLayer",
    "COMPONENT": "groupLayer", "COMPONENT_SET": "groupLayer",
    "RECTANGLE": "shapeLayer", "VECTOR": "shapeLayer", "ELLIPSE": "shapeLayer",
    "LINE": "shapeLayer", "POLYGON": "shapeLayer", "STAR": "shapeLayer",
    "BOOLEAN_OPERATION": "shapeLayer",
}


def parse_ref(ref, base):
    parts = urllib.parse.urlsplit(ref[len(base):])
    if parts.path not in ("", "/"):
        raise ValueError(f"须是平台首页链接 {base}/?project=…&design=…: {ref}")
    query = urllib.parse.parse_qs(parts.query)
    ids = {}
    for key in ("project", "design"):
        values = query.get(key, [])
        if len(values) != 1 or not re.fullmatch(r"[0-9]+", values[0]) or int(values[0]) == 0:
            raise ValueError(f"链接须带且只带一个正整数 {key}=…: {ref}")
        ids[f"{key}_id"] = int(values[0])
    return ids


# ---------------------------------------------------------------- HTTP

def cookie_from_file(path):
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line.startswith(COOKIE_ENV + "="):
                continue
            v = line.split("=", 1)[1].strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            return v or None
    return None


def resolve_cookie(cli_cookie):
    return (cli_cookie or os.environ.get(COOKIE_ENV, "").strip()
            or cookie_from_file(COOKIE_FILE))


def default_http_get(url, cookie, timeout=30):
    req = urllib.request.Request(url, headers={
        "Cookie": cookie,
        "User-Agent": "Mozilla/5.0",
        "Accept-Encoding": "gzip",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        ce = (resp.headers.get("Content-Encoding") or "").lower()
        if ce == "gzip" or data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        return data


# ---------------------------------------------------------------- 选图

def display_name(asset):
    name = asset.get("name") or ""
    return name[len(FIGMA_PREFIX):] if name.startswith(FIGMA_PREFIX) else name


class FetchError(Exception):
    def __init__(self, err_type, detail):
        super().__init__(detail)
        self.err_type = err_type


def request_json(http_get, url, cookie):
    try:
        return json.loads(http_get(url, cookie))
    except Exception as e:
        if isinstance(e, urllib.error.HTTPError) and e.code == 401:  # 平台对缺失/失效会话一律 401
            raise FetchError("cookie_rejected", f"Cookie 无效或已过期({url})：{COOKIE_HINT}")
        raise FetchError("request_failed", f"{url}: {e}")


def platform_url(base, path):
    """服务端给的资源路径只能是本平台的绝对路径，否则 cookie 会被带到别的主机。"""
    if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
        raise ValueError(f"资源路径不是本平台路径: {path!r}")
    return f"{base}{path}"


def root_id(layers):
    """画板本身不在图层列表里：唯一一个找不到的 parentId 就是画板 id；不唯一返回 None。"""
    ids = {l["id"] for l in layers}
    roots = {l.get("parentId") for l in layers if l.get("parentId") not in ids}
    return roots.pop() if len(roots) == 1 else None


def check_project(projects, project_id):
    """项目不存在或无权限时 assets 接口一律 403，先查可见项目才能报清楚。"""
    if not any(p.get("id") == project_id for p in projects):
        raise FetchError("project_not_found",
                         f"当前账号可见的项目里没有 project={project_id}(链接有误，或账号无该项目权限)")


def pick_asset(assets, design_id):
    """链接钉住的那次上传；与平台前端打开链接一致，只认有 preview 的 UI 图。"""
    for a in assets:
        if a.get("id") == design_id and a.get("kind") == "ui" and a.get("preview"):
            return a
    raise FetchError("design_not_found",
                     f"项目里没有可打开的 UI 设计图 design={design_id}(链接有误或设计图已删除)")


# ---------------------------------------------------------------- 转换

def css_color(hex_color, opacity):
    if opacity >= 1:
        return hex_color
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r},{g},{b},{round(opacity, 3):g})"


def text_metric(value, unit, font_size):
    """平台给 PIXELS / PERCENT(相对字号)，蓝湖统一用 px；AUTO 无值。"""
    if unit == "PIXELS":
        return value
    if unit == "PERCENT":
        return round(font_size * value / 100, 2)
    return None


def convert_layer(layer):
    ltype = layer.get("type")
    node = {
        "id": layer["id"],
        "name": layer.get("name", ""),
        "type": LAYER_TYPES.get(ltype, ltype),
        "frame": {"left": layer["x"], "top": layer["y"],
                  "width": layer["width"], "height": layer["height"]},
        "opacity": layer.get("opacity", 1),
        # 平台顺序:左上 / 右上 / 右下 / 左下
        "radius": dict(zip(("topLeft", "topRight", "bottomRight", "bottomLeft"),
                           layer.get("cornerRadii") or (0, 0, 0, 0))),
    }
    if ltype == "BOOLEAN_OPERATION":
        # 平台不给运算类型；bind 只看 paths 里有无 booleanOperation 来标需切图
        node["paths"] = [{"booleanOperation": "unknown"}]
    fill = None
    if layer.get("fillColor") and layer.get("fillOpacity", 0) > 0:
        fill = css_color(layer["fillColor"], layer["fillOpacity"])

    if ltype == "TEXT":
        size = layer.get("fontSize")
        node["text"] = {
            "value": layer.get("textContent") or "",
            "style": {
                "font": {
                    "name": layer.get("fontFamily"),
                    "size": size,
                    "fontWeight": layer.get("fontWeight"),
                    "align": (layer.get("textAlign") or "").lower() or None,
                    "lineHeight": text_metric(layer.get("lineHeightValue"),
                                              layer.get("lineHeightUnit"), size),
                    "letterSpacing": text_metric(layer.get("letterSpacingValue"),
                                                 layer.get("letterSpacingUnit"), size),
                },
                # 文字图层的填充色就是字色
                "color": {"value": fill},
            },
        }
        return node

    style = {}
    if fill:
        style["fills"] = [{"type": "color", "isEnabled": True, "color": {"value": fill}}]
    if layer.get("strokeColor") and layer.get("strokeOpacity", 0) > 0:
        style["borders"] = [{
            "isEnabled": True,
            "width": layer.get("strokeWeight"),
            "color": {"value": css_color(layer["strokeColor"], layer["strokeOpacity"])},
        }]
    if style:
        node["style"] = style
    return node


def build_artboard(layers, name):
    """平台给的是扁平图层 + parentId，按 parentId 还原嵌套。坐标已是相对画板的绝对坐标。"""
    root = root_id(layers)
    if root is None:
        raise FetchError("bad_design_data",
                         f"「{name}」没有图层数据或找不到唯一画板根节点，请用新版插件重新上传")
    artboard = {
        "id": root, "name": name, "type": "artboard",
        "frame": {"left": 0, "top": 0,
                  "width": layers[0]["frameWidth"], "height": layers[0]["frameHeight"]},
        "layers": [],
    }
    nodes = {l["id"]: convert_layer(l) for l in layers}
    for l in layers:
        parent = artboard if l["parentId"] == root else nodes[l["parentId"]]
        parent.setdefault("layers", []).append(nodes[l["id"]])
    # parentId 成环的图层挂不到画板下，不能悄悄丢掉
    if count_layers(artboard) != len(layers):
        raise FetchError("bad_design_data",
                         f"「{name}」有图层挂不到画板根节点上，请用新版插件重新上传")
    return artboard


def count_layers(node):
    return sum(1 + count_layers(c) for c in node.get("layers", []))


def mark_exports(node, ids):
    """与蓝湖一致：导出过切图的节点带 hasExportImage + image，bind enrich 据此不再要求补图。
    远端地址要 cookie，所以 URL 为空，图走 slices.json 的 local_png。"""
    if node.get("id") in ids:
        node.update(hasExportImage=True, image={"imageUrl": None, "svgUrl": None})
    for child in node.get("layers", []):
        mark_exports(child, ids)


# ---------------------------------------------------------------- 切图

def same_box(a, b):
    return all(abs(a[k] - b[k]) < 0.5 for k in ("x", "y", "width", "height"))


def plan_slices(chosen, base, warnings):
    """平台每个导出倍率是一条独立切图(名为「选择框 · PNG @2x」，重名再加「 2」)，
    且不记录图层 id。按 名称+位置尺寸 归组，再按位置尺寸(同名优先)挂到图层上。
    只读数据不落盘，结构不对在这里就抛出。"""
    layers = chosen["layers"]
    artboard_box = {"x": 0, "y": 0,
                    "width": layers[0]["frameWidth"], "height": layers[0]["frameHeight"]}
    groups = {}
    for s in chosen.get("slices") or []:
        m = SLICE_NAME.match(s.get("name") or "")
        name, scale = (m["base"], float(m["scale"])) if m else (s.get("name"), 1.0)
        # 画板自身的导出(以画板名命名) = cover，不算切图；同尺寸的全屏背景图照常保留
        if name == display_name(chosen) and same_box(s, artboard_box):
            continue
        key = (name, s["x"], s["y"], s["width"], s["height"])
        groups.setdefault(key, {})[scale] = s

    planned = []
    for (name, x, y, w, h), scales in groups.items():
        box = {"x": x, "y": y, "width": w, "height": h}
        matches = [l for l in layers if same_box(l, box)]
        named = [l for l in matches if l.get("name") == name]
        hit = named if named else matches
        layer_id = hit[0]["id"] if len(hit) == 1 else None
        if layer_id is None:
            warnings.append(f"切图「{name}」({x},{y},{w}x{h}) 匹配到 {len(hit)} 个图层，未挂到图层上")

        # 下游(blueprint)只用 local_png，只下最大倍率
        largest = scales[max(scales)]
        entry = {
            "id": layer_id,
            "name": name,
            "frame": {"left": x, "top": y, "width": w, "height": h},
            "position": {"x": x, "y": y},
            "logical_size": {"width": w, "height": h},
            # 远端切图需要登录 cookie，下游只用本地文件
            "download_url": None,
            "svg_url": None,
            "scale_urls": None,
            "local_png": None,
            "local_svg": None,
        }
        # id 拼进文件名，只收整数，免得写出 out-dir 或两张切图写成同一个文件
        if type(largest["id"]) is not int:
            raise ValueError(f"切图 id 不是整数: {largest['id']!r}")
        planned.append((entry, platform_url(base, largest["preview"]),
                        f"assets/{largest['id']}.png"))

    # blueprint 按 id 取切图，一个图层对应多张切图会互相覆盖：都不挂
    owners = Counter(entry["id"] for entry, *_ in planned if entry["id"])
    for entry, *_ in planned:
        if owners[entry["id"]] > 1:
            warnings.append(f"切图「{entry['name']}」与其他切图挂到同一图层 {entry['id']}，未挂到图层上")
            entry["id"] = None
    return planned


def download_slices(planned, out_dir, cookie, http_get, warnings):
    result = []
    for entry, url, rel in planned:
        try:
            data = http_get(url, cookie)
        except Exception as e:
            warnings.append(f"切图下载失败「{entry['name']}」: {e}")
        else:
            (out_dir / "assets").mkdir(parents=True, exist_ok=True)
            (out_dir / rel).write_bytes(data)
            entry["local_png"] = rel
        result.append(entry)
    return result


# ---------------------------------------------------------------- main

def emit(payload, code):
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return code


def emit_error(err_type, detail, code=1):
    return emit({"ok": False, "errors": [{"type": err_type, "detail": detail}]}, code)


def fetch(ref, base, out_dir, cookie=None, skip_cover=False, http_get=None):
    parsed = parse_ref(ref, base)
    cookie = resolve_cookie(cookie)
    if not cookie:
        return emit_error("no_cookie", f"缺少平台 Cookie：{COOKIE_HINT}")
    http_get = http_get or default_http_get

    # 定位与转换全部成功之前不落任何产物
    try:
        projects = request_json(http_get, f"{base}/api/projects", cookie).get("projects") or []
        check_project(projects, parsed["project_id"])
        assets = request_json(http_get, f"{base}/api/projects/{parsed['project_id']}/assets",
                              cookie).get("assets") or []
        chosen = pick_asset(assets, parsed["design_id"])
        name = display_name(chosen)
        artboard = build_artboard(chosen.get("layers") or [], name)
        # 顶层与蓝湖一致(meta + artboard)，bind.py 各命令自己取 .artboard；平台缺省按安卓
        design = {"meta": {"device": chosen.get("figmaPlatform") or "android",
                           "plugin": "selfhost",
                           "asset_id": chosen["id"]},
                  "artboard": artboard}
        warnings = []
        planned = plan_slices(chosen, base, warnings)
        mark_exports(artboard, {entry["id"] for entry, *_ in planned if entry["id"]})
        cover_url = None if skip_cover else platform_url(base, chosen["preview"])
    except FetchError as e:
        return emit_error(e.err_type, str(e))
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        return emit_error("bad_design_data",
                          f"平台返回的数据结构不符合预期({type(e).__name__}: {e})")

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "design.json").write_text(
        json.dumps(design, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    slices = download_slices(planned, out_dir, cookie, http_get, warnings)
    (out_dir / "slices.json").write_text(
        json.dumps({"slices": slices}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    # 与蓝湖一致：cover 下载失败记 warning，cover_image 为 null(crop 步骤将无输入)
    cover_path = None
    if cover_url:
        try:
            data = http_get(cover_url, cookie)
        except Exception as e:
            warnings.append(f"cover 下载失败: {e}")
        else:
            cover_path = out_dir / "cover.png"
            cover_path.write_bytes(data)

    summary = {
        "ok": True,
        "dir": str(out_dir),
        "design_json": str(out_dir / "design.json"),
        "slices_json": str(out_dir / "slices.json"),
        "cover_image": str(cover_path) if cover_path else None,
        "design_name": name,
        "design_id": chosen["id"],
        "slices_total": len(slices),
        "slices_downloaded": sum(1 for s in slices if s["local_png"]),
    }
    if warnings:
        summary["warnings"] = warnings
    return emit(summary, 0)
