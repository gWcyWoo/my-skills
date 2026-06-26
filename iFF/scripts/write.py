#!/usr/bin/env python3
"""
write.py — Read fetch.py's raw.json and write the full spec.md (4 H1 sections)
to disk. The orchestrator never sees the markdown content — it only gets a
small summary on stdout.

Usage:
    python3 write.py --input <raw.json> --output <spec.md>

Stdout: one line JSON with {output, text_layers, shape_layers, group_layers, assets}
Stderr: parse diagnostics (counts).
Exit:   0 success | 1 invalid JSON | 2 missing artboard | 3 IO error.

spec.md structure (exact, do not change):
  # 文件描述           ← name + Lanhu URL (auto-filled from raw.json)
  # UI描述             ← canvas + text/shape/group tables + assets + tree
  # 交互描述           ← placeholder
  # 数据描述           ← placeholder

Complex sub-objects (letterSpacing/lineHeight/border/fill/shadow/radius) are
emitted as compact JSON inside table cells so the output is 1:1 reversible
with the original Figma JSON. No values are inferred or summarized away.
"""

import argparse
import json
import os
import sys


# ----- formatting helpers -----

def fmt_num(v, ndigits=2):
    """Round a float to ndigits but drop trailing zeros so 33.0 -> '33'."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        return str(v)
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if f.is_integer():
        return str(int(f))
    return f"{f:.{ndigits}f}".rstrip("0").rstrip(".")


def color_to_str(c):
    """Reduce a Figma color dict to its 'rgba(...)' string for compact display."""
    if not isinstance(c, dict):
        return c
    v = c.get("value")
    if v:
        return v
    a = c.get("a", 1)
    r = round(c.get("r", 0) * 255)
    g = round(c.get("g", 0) * 255)
    b = round(c.get("b", 0) * 255)
    return f"rgba({r},{g},{b},{fmt_num(a)})"


# Keys that are always empty / boilerplate in the Lanhu Figma JSON; dropping them
# keeps spec.md cells readable without losing usable data. Anything genuinely
# carrying values (boundVariables when a token IS bound, etc.) is preserved.
_NOISE_KEYS = {"boundVariables"}


def normalize_for_cell(obj):
    """Recursively prepare a value for cell_json:
    - replace Figma color dicts (with r/g/b/value keys) with their rgba string
    - drop empty dicts / empty lists / None
    - drop noise keys (`boundVariables: {}`)
    Lossless for any field that actually carries data.
    """
    if isinstance(obj, dict):
        if "r" in obj and "g" in obj and "b" in obj and "value" in obj:
            return color_to_str(obj)
        out = {}
        for k, v in obj.items():
            if k in _NOISE_KEYS and (v in ({}, [], None) or v == 0):
                continue
            if v is None or v == {} or v == []:
                continue
            nv = normalize_for_cell(v)
            if nv is None or nv == {} or nv == []:
                continue
            out[k] = nv
        return out
    if isinstance(obj, list):
        cleaned = [normalize_for_cell(x) for x in obj]
        return [x for x in cleaned if x not in (None, {}, [])]
    return obj


def cell_json(obj):
    """Render a cell as compact JSON (lossless after normalize_for_cell).
    Returns '' for an empty value so the table cell is blank rather than '{}'.
    """
    norm = normalize_for_cell(obj)
    if norm in (None, {}, []):
        return ""
    if isinstance(norm, str):
        return norm
    return json.dumps(norm, ensure_ascii=False, separators=(",", ":"))


def cell_json_list(items):
    """Render a list of objects (e.g. multiple shadows) as a JSON array cell."""
    if not items:
        return ""
    cleaned = [normalize_for_cell(it) for it in items]
    cleaned = [x for x in cleaned if x not in (None, {}, [])]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return json.dumps(cleaned[0], ensure_ascii=False, separators=(",", ":"))
    return json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))


def md_escape(s):
    if s is None:
        return ""
    return str(s).replace("|", r"\|").replace("\n", " ").strip()


# ----- layer extraction -----

def collect_layers(node, parent_path=""):
    """Walk the artboard tree, yield (typed_record, path) per layer."""
    name = node.get("name", "")
    typ = node.get("type", "")
    path = f"{parent_path}/{name}" if parent_path else name
    yield (typ, node, path)
    for sub in node.get("layers") or []:
        yield from collect_layers(sub, path)


def extract_text(layer, path):
    f = layer.get("frame") or {}
    text = layer.get("text") or {}
    ts = text.get("style") or {}
    font = ts.get("font") or {}
    styles = text.get("styles") or []
    return {
        "id": layer.get("id"),
        "name": layer.get("name", ""),
        "path": path,
        "x": fmt_num(f.get("left")),
        "y": fmt_num(f.get("top")),
        "w": fmt_num(f.get("width")),
        "h": fmt_num(f.get("height")),
        "content": ts.get("content", text.get("value", "")),
        "font_ps": font.get("postScriptName", ""),
        "font_name": font.get("name", ""),
        "size": fmt_num(font.get("size")),
        "weight": fmt_num(font.get("fontWeight")),
        "color": cell_json(ts.get("color")),
        "align": font.get("align", ""),
        "valign": font.get("verticalAlignment", ""),
        "letterSpacing": cell_json(font.get("letterSpacing")),
        "lineHeight": cell_json(font.get("lineHeight")),
        "italic": font.get("italic", False),
        "underline": font.get("underline"),
        "linethrough": font.get("linethrough"),
        "opacity": fmt_num(layer.get("opacity", 1)),
        "rotation": fmt_num(layer.get("rotation", 0)),
        "visible": layer.get("visible", True),
        # Multi-style runs (when text mixes styles within one string).
        # If only one entry == single-style; we still emit it for round-trip fidelity.
        "styles_runs": cell_json_list(styles) if len(styles) > 1 else "",
    }


def extract_shape(layer, path):
    f = layer.get("frame") or {}
    style = layer.get("style") or {}
    fills = style.get("fills") or []
    borders = style.get("borders") or []
    shadows = style.get("shadows") or []
    blurs = style.get("blurs") or []
    paths = layer.get("paths") or []
    primary_path_type = paths[0].get("type") if paths else ""

    # Some shapes have per-path radius that overrides layer.radius
    per_path_radius = paths[0].get("radius") if paths else None
    radius = per_path_radius or layer.get("radius") or {}

    return {
        "id": layer.get("id"),
        "name": layer.get("name", ""),
        "path": path,
        "shape_type": primary_path_type,
        "x": fmt_num(f.get("left")),
        "y": fmt_num(f.get("top")),
        "w": fmt_num(f.get("width")),
        "h": fmt_num(f.get("height")),
        "fills": cell_json_list(fills),
        "borders": cell_json_list(borders),
        "radius": cell_json(radius),
        "shadows": cell_json_list(shadows),
        "blurs": cell_json_list(blurs),
        "opacity": fmt_num(layer.get("opacity", 1)),
        "rotation": fmt_num(layer.get("rotation", 0)),
        "has_export": layer.get("hasExportImage") or layer.get("hasExportDDSImage", False),
        "is_mask": layer.get("isMask", False),
        "visible": layer.get("visible", True),
    }


def extract_group(layer, path):
    f = layer.get("frame") or {}
    style = layer.get("style") or {}
    fills = style.get("fills") or []
    borders = style.get("borders") or []
    shadows = style.get("shadows") or []
    blurs = style.get("blurs") or []
    paths = layer.get("paths") or []
    # Figma Frame/Group 的圆角常常落在 paths[0].radius，不在 layer.radius。
    # 见 extract_shape 同样做法。早前 group 分支漏了这层 fallback，按钮的圆角
    # 因此被当成 0 输出。
    per_path_radius = paths[0].get("radius") if paths else None
    radius = per_path_radius or layer.get("radius") or {}
    return {
        "id": layer.get("id"),
        "name": layer.get("name", ""),
        "path": path,
        "type": layer.get("type"),
        "x": fmt_num(f.get("left")),
        "y": fmt_num(f.get("top")),
        "w": fmt_num(f.get("width")),
        "h": fmt_num(f.get("height")),
        "child_count": len(layer.get("layers") or []),
        # Figma 里 Frame / Group 也可以带 fill/border/shadow/radius —— 设计师常把
        # 按钮、卡片做成带样式的 Frame。早前版本只取几何信息，这些样式被丢失。
        "fills": cell_json_list(fills),
        "borders": cell_json_list(borders),
        "radius": cell_json(radius),
        "shadows": cell_json_list(shadows),
        "blurs": cell_json_list(blurs),
        "opacity": fmt_num(layer.get("opacity", 1)),
        "rotation": fmt_num(layer.get("rotation", 0)),
        "is_mask": layer.get("isMask", False),
        "visible": layer.get("visible", True),
    }


# ----- rendering -----

def render_canvas_section(figma):
    out = ["## 画布", ""]
    artboard = figma.get("artboard") or {}
    af = artboard.get("frame") or {}
    meta = figma.get("meta") or {}
    host = meta.get("host") or {}
    plugin = meta.get("plugin") or {}

    out.append("| 字段 | 值 |")
    out.append("| --- | --- |")
    out.append(f"| Artboard id | `{md_escape(artboard.get('id',''))}` |")
    out.append(f"| Artboard name | {md_escape(artboard.get('name',''))} |")
    out.append(f"| 宽 | `{fmt_num(af.get('width'))}` |")
    out.append(f"| 高 | `{fmt_num(af.get('height'))}` |")
    out.append(f"| 设备 | `{md_escape(meta.get('device',''))}` |")
    out.append(f"| Slice scale | `{fmt_num(meta.get('sliceScale'))}` |")
    out.append(f"| Source host | `{md_escape(host.get('name',''))} {md_escape(host.get('version',''))}` |")
    out.append(f"| Plugin | `{md_escape(plugin.get('name',''))} {md_escape(plugin.get('version',''))}` |")
    out.append(f"| Opacity | `{fmt_num(artboard.get('opacity',1))}` |")
    out.append("")
    return out


def render_text_table(rows):
    if not rows:
        return ["## 文字图层", "", "(无)", ""]
    out = ["## 文字图层（textLayer）", ""]
    out.append(f"共 {len(rows)} 个。letterSpacing / lineHeight / color 列保留原 JSON 字段（紧凑序列化）以确保 1:1 还原；styles_runs 仅在多段混排时填值。")
    out.append("")
    out.append("| id | name | x | y | w | h | 文本 | 字体 | size | weight | 颜色 | align | letterSpacing | lineHeight | opacity | styles_runs |")
    out.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in rows:
        out.append(
            "| `{id}` | {name} | {x} | {y} | {w} | {h} | {content} | {font} | {size} | {weight} | {color} | {align} | {ls} | {lh} | {opacity} | {runs} |".format(
                id=md_escape(r["id"]),
                name=md_escape(r["name"]),
                x=r["x"], y=r["y"], w=r["w"], h=r["h"],
                content=md_escape(r["content"]),
                font=md_escape(r["font_ps"] or r["font_name"]),
                size=r["size"], weight=r["weight"],
                color=md_escape(r["color"]),
                align=md_escape(r["align"]),
                ls=md_escape(r["letterSpacing"]),
                lh=md_escape(r["lineHeight"]),
                opacity=r["opacity"],
                runs=md_escape(r["styles_runs"]),
            )
        )
    out.append("")
    return out


def render_shape_table(rows):
    if not rows:
        return ["## 形状图层", "", "(无)", ""]
    out = ["## 形状图层（shapeLayer）", ""]
    out.append(f"共 {len(rows)} 个。fills / borders / shadows / blurs / radius 列保留原 JSON 字段（紧凑序列化），多元素时按数组输出，无内容则留空。")
    out.append("")
    out.append("| id | name | type | x | y | w | h | fills | borders | radius | shadows | blurs | opacity | rotation | export | mask |")
    out.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in rows:
        out.append(
            "| `{id}` | {name} | {st} | {x} | {y} | {w} | {h} | {fills} | {borders} | {radius} | {shadows} | {blurs} | {opacity} | {rot} | {exp} | {mask} |".format(
                id=md_escape(r["id"]),
                name=md_escape(r["name"]),
                st=md_escape(r["shape_type"]),
                x=r["x"], y=r["y"], w=r["w"], h=r["h"],
                fills=md_escape(r["fills"]),
                borders=md_escape(r["borders"]),
                radius=md_escape(r["radius"]),
                shadows=md_escape(r["shadows"]),
                blurs=md_escape(r["blurs"]),
                opacity=r["opacity"],
                rot=r["rotation"],
                exp="✓" if r["has_export"] else "",
                mask="✓" if r["is_mask"] else "",
            )
        )
    out.append("")
    return out


def render_group_table(rows):
    if not rows:
        return []
    out = ["## 图组 / 子画板（groupLayer / artboard）", ""]
    out.append(
        f"共 {len(rows)} 个。Figma 中 Frame / Group 也可携带 fill / border / shadow / radius —— "
        "设计师常用 Frame 做按钮、卡片、装饰容器，这些样式过去被丢，现已补全。"
    )
    out.append("")
    out.append("| id | type | name | x | y | w | h | child | fills | borders | radius | shadows | blurs | opacity | rotation | mask |")
    out.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in rows:
        out.append(
            "| `{id}` | {type} | {name} | {x} | {y} | {w} | {h} | {c} | {fills} | {borders} | {radius} | {shadows} | {blurs} | {op} | {rot} | {mask} |".format(
                id=md_escape(r["id"]),
                type=md_escape(r["type"]),
                name=md_escape(r["name"]),
                x=r["x"], y=r["y"], w=r["w"], h=r["h"],
                c=r["child_count"],
                fills=md_escape(r["fills"]),
                borders=md_escape(r["borders"]),
                radius=md_escape(r["radius"]),
                shadows=md_escape(r["shadows"]),
                blurs=md_escape(r["blurs"]),
                op=r["opacity"],
                rot=r["rotation"],
                mask="✓" if r["is_mask"] else "",
            )
        )
    out.append("")
    return out


def render_assets_section(figma):
    assets = figma.get("assets") or []
    if not assets:
        return []
    out = ["## 切图资源（assets）", "", f"共 {len(assets)} 个 URL", ""]
    out.append("| # | URL |")
    out.append("| --- | --- |")
    for i, a in enumerate(assets, start=1):
        out.append(f"| {i} | {md_escape(a)} |")
    out.append("")
    return out


_FIGMA_SLICE_PREFIX_PNG = "FigmaSlicePNG"
_FIGMA_SLICE_PREFIX_SVG = "FigmaSliceSVG"


def _slice_local_path(url):
    """Mirror fetch.py's slice_filename, returning 'assets/<file>' relative path."""
    if not url:
        return ""
    base = url.rsplit("/", 1)[-1].split("?", 1)[0]
    for prefix in (_FIGMA_SLICE_PREFIX_PNG, _FIGMA_SLICE_PREFIX_SVG):
        if base.startswith(prefix):
            return f"assets/{base[len(prefix):]}"
    return f"assets/{base}"


def _collect_exportable(node, parent_path=""):
    if not isinstance(node, dict):
        return
    name = node.get("name", "")
    path = f"{parent_path}/{name}" if parent_path else name
    img = node.get("image") or {}
    if (img.get("imageUrl") or img.get("svgUrl")) and node.get("hasExportImage"):
        yield {
            "id": node.get("id"),
            "name": name,
            "layer_path": path,
            "frame": node.get("frame") or {},
            "png_url": img.get("imageUrl"),
            "svg_url": img.get("svgUrl"),
        }
    for sub in node.get("layers") or []:
        yield from _collect_exportable(sub, path)


def render_slice_mapping_section(figma):
    """List every layer with hasExportImage=True and its local slice path.

    fc / 实现端可凭这个表把 layer.id 直接映射到 Image.asset 路径。
    """
    rows = list(_collect_exportable(figma.get("artboard") or {}))
    if not rows:
        return []
    out = [
        "## 切图映射（layer → 本地切图）",
        "",
        f"共 {len(rows)} 个 hasExportImage 图层。`png` / `svg` 列填的是相对 spec.md 的路径；",
        "`fetch.py` 已把所有切图下载到同目录的 `assets/` 下，多个 layer 共用同一 URL 会指向同一个文件。",
        "",
        "| layer.id | name | path | frame (x/y/w/h) | png | svg |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        f = r["frame"]
        frame_str = f"{fmt_num(f.get('left'))}/{fmt_num(f.get('top'))}/{fmt_num(f.get('width'))}/{fmt_num(f.get('height'))}"
        png_local = _slice_local_path(r["png_url"]) if r["png_url"] else ""
        svg_local = _slice_local_path(r["svg_url"]) if r["svg_url"] else ""
        out.append(
            f"| `{md_escape(r['id'])}` | {md_escape(r['name'])} | {md_escape(r['layer_path'])} | {frame_str} | {md_escape(png_local)} | {md_escape(svg_local)} |"
        )
    out.append("")
    return out


def render_path_tree(figma, max_depth=99):
    """Optional: indented hierarchy for human reading."""
    artboard = figma.get("artboard") or {}
    out = ["## 图层树", "", "```text"]

    def walk(node, depth):
        if depth > max_depth:
            return
        prefix = "  " * depth
        nm = node.get("name") or "(unnamed)"
        tp = node.get("type", "")
        nid = node.get("id", "")
        out.append(f"{prefix}- [{tp}] {nm}  ({nid})")
        for sub in node.get("layers") or []:
            walk(sub, depth + 1)

    walk(artboard, 0)
    out.append("```")
    out.append("")
    return out


def render_ui_section(wrapper):
    """Build the body of the # UI描述 section. Returns the rendered string and
    summary counts."""
    figma = wrapper.get("figma_json") or {}
    if not figma.get("artboard"):
        raise ValueError("figma_json missing artboard")

    text_rows, shape_rows, group_rows = [], [], []
    for typ, node, path in collect_layers(figma["artboard"]):
        if path == figma["artboard"].get("name", ""):
            # skip the root artboard itself in element tables
            continue
        if typ == "textLayer":
            text_rows.append(extract_text(node, path))
        elif typ == "shapeLayer":
            shape_rows.append(extract_shape(node, path))
        elif typ in ("groupLayer", "artboard"):
            group_rows.append(extract_group(node, path))

    slice_count = sum(1 for _ in _collect_exportable(figma.get("artboard") or {}))

    out = []
    out += render_canvas_section(figma)
    out += render_text_table(text_rows)
    out += render_shape_table(shape_rows)
    out += render_group_table(group_rows)
    out += render_assets_section(figma)
    out += render_slice_mapping_section(figma)
    out += render_path_tree(figma)

    counts = {
        "text_layers": len(text_rows),
        "shape_layers": len(shape_rows),
        "group_layers": len(group_rows),
        "assets": len(figma.get("assets") or []),
        "exportable_slices": slice_count,
    }
    return "\n".join(out), counts


def build_spec_md(wrapper):
    """Assemble the full spec.md (4 H1 sections). Returns (markdown, counts)."""
    ui_body, counts = render_ui_section(wrapper)
    parts = [
        "# 文件描述",
        "",
        f"- 名字: {wrapper.get('design_name','')}",
        f"- 原始路径: {wrapper.get('lanhu_url','')}",
        "",
        "# UI描述",
        "",
        ui_body.rstrip(),
        "",
        "# 交互描述",
        "",
        "> 待开发人员填写",
        "",
        "# 数据描述",
        "",
        "> 待开发人员填写",
        "",
    ]
    return "\n".join(parts), counts


def main():
    ap = argparse.ArgumentParser(description="Render raw.json into a complete spec.md (4 H1 sections).")
    ap.add_argument("--input", "-i", required=True, help="Path to raw.json from fetch.py")
    ap.add_argument("--output", "-o", required=True, help="Path to write spec.md")
    args = ap.parse_args()

    try:
        with open(args.input, encoding="utf-8") as f:
            wrapper = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: input not found: {args.input}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid JSON in {args.input}: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        md, counts = build_spec_md(wrapper)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)

    try:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(md)
    except OSError as e:
        print(f"ERROR: failed to write spec.md: {e}", file=sys.stderr)
        sys.exit(3)

    summary = {"output": os.path.abspath(args.output), **counts}
    json.dump(summary, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
