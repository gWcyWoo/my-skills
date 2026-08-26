#!/usr/bin/env python3
"""ICP Stage 1 — bind: 将模型语义分组绑定到蓝湖设计 JSON 节点。

四个子命令:
  prepare   从蓝湖 sketch JSON 生成节点摘要(供模型分组时参考)
  bind      接收模型分组结果，绑定设计数据，检查完备性
  clean     从绑定结果中删除系统组件
  enrich    合并切片数据(多倍率URL)，标记缺失图片资源的节点
"""

import argparse
import json
import sys
from pathlib import Path


# ---------------------------------------------------------------- 系统组件模式

SYSTEM_COMPONENT_PATTERNS = [
    "Home Indicator",
    "Status Bar",
    "StatusBar",
    "status_bar",
    "home_indicator",
]


def is_system_component(node):
    name = node.get("name", "")
    comp = node.get("componentName", "")
    for pat in SYSTEM_COMPONENT_PATTERNS:
        if pat.lower() in name.lower() or pat.lower() in comp.lower():
            return True
    return False


def _member_is_system(member):
    """判断 bound 输出的 member 是否是系统组件（按 is_system 标记或 name/component_name）。"""
    if member.get("is_system"):
        return True
    name = member.get("name", "").strip()
    comp = member.get("component_name", "").strip()
    for pat in SYSTEM_COMPONENT_PATTERNS:
        if pat.lower() in name.lower() or pat.lower() in comp.lower():
            return True
    return False


# ---------------------------------------------------------------- 树操作

def build_index(artboard):
    """递归建 id→node 索引，同时记录父子关系。"""
    idx = {}
    parent_map = {}

    def walk(node, parent_id=None):
        nid = node.get("id")
        if not nid:
            return
        idx[nid] = node
        parent_map[nid] = parent_id
        for child in node.get("layers", []):
            walk(child, nid)

    walk(artboard)
    return idx, parent_map



def extract_node_summary(node):
    """提取节点摘要，供模型分组参考。"""
    summary = {
        "id": node.get("id"),
        "name": node.get("name"),
        "type": node.get("type"),
    }

    frame = node.get("frame")
    if frame:
        summary["size"] = f"{frame.get('width', 0):.0f}x{frame.get('height', 0):.0f}"

    if node.get("text"):
        text = node["text"]
        summary["text"] = text.get("value", "")[:80]

    if node.get("componentName"):
        summary["component"] = node["componentName"]

    if node.get("image"):
        summary["has_image"] = True

    if node.get("hasExportImage"):
        summary["has_export"] = True

    child_count = len(node.get("layers", []))
    if child_count > 0:
        summary["children"] = child_count

    return summary


def extract_design_data(node):
    """提取节点的完整设计数据，供组件实现参考。"""
    data = {
        "id": node.get("id"),
        "name": node.get("name"),
        "type": node.get("type"),
        "frame": node.get("frame"),
        "visible": node.get("visible", True),
        "opacity": node.get("opacity", 1),
    }

    # 圆角
    radius = node.get("radius", {})
    if any(radius.get(k, 0) > 0 for k in ["topLeft", "topRight", "bottomLeft", "bottomRight"]):
        data["radius"] = radius

    # 样式
    style = node.get("style", {})

    # 填充
    fills = []
    for f in style.get("fills", []):
        if not f.get("isEnabled", True):
            continue
        if f["type"] == "color":
            fills.append({"type": "color", "value": f["color"].get("value")})
        elif f["type"] == "gradient":
            g = f["gradient"]
            fills.append({
                "type": "gradient",
                "gradient_type": g.get("type"),
                "stops": [{"color": s["color"].get("value"), "position": s.get("position")}
                          for s in g.get("stops", [])],
            })
        elif f["type"] == "image":
            fills.append({"type": "image", "url": f.get("image", {}).get("url")})
    if fills:
        data["fills"] = fills

    # 边框
    borders = []
    for b in style.get("borders", []):
        if not b.get("isEnabled", True):
            continue
        borders.append({
            "width": b.get("width"),
            "color": b.get("color", {}).get("value"),
            "style": b.get("style"),
        })
    if borders:
        data["borders"] = borders

    # 阴影
    shadows = []
    for s in style.get("shadows", []):
        if not s.get("isEnabled", True):
            continue
        shadows.append({
            "x": s.get("x"), "y": s.get("y"),
            "blur": s.get("blur"), "spread": s.get("spread"),
            "color": s.get("color", {}).get("value"),
            "inset": s.get("inset", False),
        })
    if shadows:
        data["shadows"] = shadows

    # 模糊
    blurs = []
    for bl in style.get("blurs", []):
        if not bl.get("isEnabled", True):
            continue
        blurs.append({"type": bl.get("type"), "radius": bl.get("radius")})
    if blurs:
        data["blurs"] = blurs

    # 文字
    if node.get("text"):
        text = node["text"]
        text_data = {"value": text.get("value", "")}
        spans = text.get("styles", [])
        if not spans and text.get("style"):
            spans = [text["style"]]
        text_spans = []
        for s in spans:
            font = s.get("font", {})
            lh = font.get("lineHeight")
            text_spans.append({
                "content": s.get("content", ""),
                "font": font.get("name"),
                "size": font.get("size"),
                "weight": font.get("fontWeight"),
                "align": font.get("align"),
                "line_height": lh.get("value") if isinstance(lh, dict) else lh,
                "color": s.get("color", {}).get("value"),
                "letter_spacing": font.get("letterSpacing", {}).get("value")
                    if isinstance(font.get("letterSpacing"), dict) else font.get("letterSpacing"),
            })
        text_data["spans"] = text_spans
        data["text"] = text_data

    # 图片
    if node.get("image"):
        data["image"] = {
            "png": node["image"].get("imageUrl"),
            "svg": node["image"].get("svgUrl"),
        }

    # 组件
    if node.get("componentName"):
        data["component_name"] = node["componentName"]
    if node.get("componentProperties"):
        data["component_properties"] = node["componentProperties"]

    # sharedStyle
    if node.get("sharedStyle"):
        data["shared_style"] = node["sharedStyle"]

    return data


# ---------------------------------------------------------------- cmd: prepare

def cmd_prepare(args):
    """读蓝湖 JSON，输出节点摘要树(供模型做语义分组)。"""
    design = json.loads(Path(args.design_json).read_text(encoding="utf-8"))
    artboard = design.get("artboard", {})
    meta = design.get("meta", {})

    def summarize_tree(node, depth=0, parent_system=False):
        s = extract_node_summary(node)
        s["depth"] = depth
        s["is_system"] = parent_system or is_system_component(node)
        children = []
        for child in node.get("layers", []):
            children.append(summarize_tree(child, depth + 1, s["is_system"]))
        if children:
            s["layers"] = children
        return s

    tree = summarize_tree(artboard)

    # 扁平列表（无层级，方便模型快速扫描）
    flat = []
    stack = [(artboard, 0, False)]
    while stack:
        node, depth, parent_sys = stack.pop()
        entry = extract_node_summary(node)
        entry["depth"] = depth
        entry["is_system"] = parent_sys or is_system_component(node)
        flat.append(entry)
        for child in reversed(node.get("layers", [])):
            stack.append((child, depth + 1, entry["is_system"]))

    out = {
        "meta": {
            "device": meta.get("device"),
            "plugin": meta.get("plugin"),
            "artboard_name": artboard.get("name"),
            "artboard_frame": artboard.get("frame"),
        },
        "total_nodes": len(flat),
        "tree": tree,
        "flat": flat,
    }

    if args.ui_desc:
        out["ui_description"] = args.ui_desc

    output_path = Path(args.output) if args.output else None
    text = json.dumps(out, ensure_ascii=False, indent=2) + "\n"
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
        print(json.dumps({"ok": True, "output": str(output_path), "total_nodes": len(flat)}))
    else:
        print(text)
    return 0


# ---------------------------------------------------------------- cmd: bind

def cmd_bind(args):
    """接收模型分组，绑定设计数据，检查完备性。

    分组格式:
    {
      "groups": [
        {
          "name": "导航栏",
          "role": "navigation",
          "node_ids": ["92:2448", "I92:2448;70:624", ...]
        },
        ...
      ]
    }

    node_ids 中的每个 id，脚本会自动包含其后代节点——但遇到
    被其他组显式声明的节点时停止展开（该节点及其后代归属其他组）。
    """
    design = json.loads(Path(args.design_json).read_text(encoding="utf-8"))
    grouping = json.loads(Path(args.grouping).read_text(encoding="utf-8"))
    artboard = design.get("artboard", {})
    idx, parent_map = build_index(artboard)
    all_ids = set(idx.keys())

    # 预计算 is_system 集合（含系统节点的所有子孙）
    system_ids = set()
    def _mark_system(node, parent_sys=False):
        nid = node.get("id")
        is_sys = parent_sys or is_system_component(node)
        if is_sys and nid:
            system_ids.add(nid)
        for child in node.get("layers", []):
            _mark_system(child, is_sys)
    _mark_system(artboard)

    # 收集所有组的显式 node_ids（用于子树展开时的边界检测）
    all_explicit = {}
    for group in grouping.get("groups", []):
        for nid in group.get("node_ids", []):
            all_explicit[nid] = group.get("name", "unnamed")

    def collect_owned_ids(node_id, own_group):
        """展开子树，遇到被其他组显式声明的节点就停。"""
        ids = []
        stack = [node_id]
        while stack:
            nid = stack.pop()
            if nid != node_id and nid in all_explicit and all_explicit[nid] != own_group:
                continue
            ids.append(nid)
            node = idx.get(nid)
            if node:
                for child in node.get("layers", []):
                    cid = child.get("id")
                    if cid:
                        stack.append(cid)
        return ids

    # 绑定
    bound_ids = set()
    components = []
    errors = []

    for group in grouping.get("groups", []):
        gname = group.get("name", "unnamed")
        members = []
        group_ids = set()

        for nid in group.get("node_ids", []):
            if nid not in idx:
                errors.append({"type": "unknown_node", "group": gname, "node_id": nid})
                continue
            owned = collect_owned_ids(nid, gname)
            group_ids.update(owned)

        # 检查重复绑定
        overlap = group_ids & bound_ids
        if overlap:
            errors.append({
                "type": "duplicate_binding",
                "group": gname,
                "overlapping_ids": sorted(overlap)[:10],
            })
            group_ids -= overlap

        bound_ids.update(group_ids)

        for nid in sorted(group_ids):
            m = extract_design_data(idx[nid])
            m["is_system"] = nid in system_ids
            members.append(m)

        components.append({
            "name": gname,
            "role": group.get("role", ""),
            "description": group.get("description", ""),
            "member_count": len(members),
            "members": members,
        })

    # 完备性检查
    unbound = all_ids - bound_ids
    unbound_nodes = []
    for uid in sorted(unbound):
        node = idx[uid]
        s = extract_node_summary(node)
        s["parent_id"] = parent_map.get(uid)
        parent_node = idx.get(parent_map.get(uid))
        if parent_node:
            s["parent_name"] = parent_node.get("name")
        unbound_nodes.append(s)

    result = {
        "ok": len(unbound) == 0 and len(errors) == 0,
        "total_nodes": len(all_ids),
        "bound_nodes": len(bound_ids),
        "unbound_nodes": len(unbound),
        "component_count": len(components),
        "components": components,
    }

    if unbound_nodes:
        result["unbound"] = unbound_nodes
    if errors:
        result["errors"] = errors

    output_path = Path(args.output) if args.output else None
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
    print(json.dumps({
        "ok": result["ok"],
        "total_nodes": len(all_ids),
        "bound_nodes": len(bound_ids),
        "unbound_nodes": len(unbound),
        "component_count": len(components),
        "errors": len(errors),
    }, ensure_ascii=False))

    return 0 if result["ok"] else 1


# ---------------------------------------------------------------- cmd: clean

def cmd_clean(args):
    """从绑定结果中删除系统组件组。

    按成员节点的 name/component_name 判断（与 is_system_component 同源）。
    一个 group 的全部成员都是系统组件时删除该 group。
    """
    bound = json.loads(Path(args.bound_json).read_text(encoding="utf-8"))
    removed = []
    kept = []

    for comp in bound.get("components", []):
        members = comp.get("members", [])
        non_sys = [m for m in members if not _member_is_system(m)]
        if not non_sys:
            removed.append({"name": comp["name"], "member_count": comp["member_count"]})
        else:
            comp["members"] = non_sys
            comp["member_count"] = len(non_sys)
            kept.append(comp)

    result = {
        "ok": True,
        "component_count": len(kept),
        "removed_system": removed,
        "components": kept,
    }

    output_path = Path(args.output) if args.output else None
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "component_count": len(kept),
        "removed_system": len(removed),
        "removed_names": [r["name"] for r in removed],
    }, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------- cmd: enrich

def _needs_asset(member, design_idx):
    """判断一个 member 节点是否需要图片资源但缺失。

    条件: 是 symbolInstence 或含布尔运算的 shapeLayer,
    没有 image 数据, 且子节点主要是 shapeLayer (矢量组合)。
    """
    if member.get("image"):
        return False

    ntype = member.get("type")
    nid = member.get("id")
    raw = design_idx.get(nid, {})

    if ntype == "symbolInstence":
        children = raw.get("layers", [])
        has_text_child = any(c.get("type") == "textLayer" for c in children)
        if has_text_child:
            return False
        return True

    if ntype == "shapeLayer":
        for p in raw.get("paths", []):
            if p.get("booleanOperation") is not None:
                return True

    return False


def _has_text_descendant(nid, design_idx):
    """递归检查节点后代是否含 textLayer。"""
    raw = design_idx.get(nid, {})
    for child in raw.get("layers", []):
        if child.get("type") == "textLayer":
            return True
        child_id = child.get("id")
        if child_id and _has_text_descendant(child_id, design_idx):
            return True
    return False


def cmd_enrich(args):
    """合并切片数据到已绑定组件，标记缺失资源。

    切片数据格式(lanhu_get_design_slices 返回):
    {
      "slices": [
        {
          "id": "2194:392",
          "name": "Header-backbround",
          "download_url": "...",
          "svg_url": "...",
          "scale_urls": {"1x": "...", "2x": "...", ...},
          "logical_size": {"width": 390, "height": 288}
        },
        ...
      ]
    }
    """
    bound = json.loads(Path(args.bound_json).read_text(encoding="utf-8"))
    slices_data = json.loads(Path(args.slices_json).read_text(encoding="utf-8"))

    # 建切片 id→slice 索引
    slice_idx = {}
    for s in slices_data.get("slices", []):
        sid = s.get("id")
        if sid:
            slice_idx[sid] = s

    # 建设计 JSON 索引（用于判断子节点结构）
    design_idx = {}
    if args.design_json:
        design = json.loads(Path(args.design_json).read_text(encoding="utf-8"))
        artboard = design.get("artboard", {})
        design_idx, _ = build_index(artboard)

    # 建 parent_map（用于去重：祖先已标记时子节点不再标记）
    parent_map = {}
    if args.design_json:
        design_raw = json.loads(Path(args.design_json).read_text(encoding="utf-8"))
        _, parent_map = build_index(design_raw.get("artboard", {}))

    def has_ancestor_in_set(nid, id_set):
        cur = parent_map.get(nid)
        while cur:
            if cur in id_set:
                return True
            cur = parent_map.get(cur)
        return False

    enriched_count = 0
    asset_required = []
    all_asset_ids = set()

    # 第一轮：合并切片 + 收集全局需要资源的节点 ID
    for comp in bound.get("components", []):
        for member in comp.get("members", []):
            mid = member.get("id")

            if mid in slice_idx and not _has_text_descendant(mid, design_idx):
                sl = slice_idx[mid]
                member["scale_urls"] = sl.get("scale_urls")
                member["svg_url"] = sl.get("svg_url")
                member["logical_size"] = sl.get("logical_size")
                enriched_count += 1

            if _needs_asset(member, design_idx):
                all_asset_ids.add(mid)

    # 第二轮：去重后标记
    for comp in bound.get("components", []):
        for member in comp.get("members", []):
            mid = member.get("id")
            if mid in all_asset_ids:
                if parent_map and has_ancestor_in_set(mid, all_asset_ids):
                    continue
                member["asset_required"] = True
                asset_required.append({
                    "id": mid,
                    "name": member.get("name"),
                    "type": member.get("type"),
                    "component_name": member.get("component_name"),
                    "frame": member.get("frame"),
                    "group": comp.get("name"),
                })

    result = {
        "ok": True,
        "component_count": len(bound.get("components", [])),
        "enriched_nodes": enriched_count,
        "asset_required_count": len(asset_required),
        "components": bound.get("components", []),
    }
    if asset_required:
        result["asset_required"] = asset_required

    output_path = Path(args.output) if args.output else None
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "enriched_nodes": enriched_count,
        "asset_required_count": len(asset_required),
        "asset_required_names": [a["name"] for a in asset_required],
    }, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------- cmd: crop

def cmd_crop(args):
    """为 asset_required 节点从整页截图裁切 96x96 图标。

    读取 enrich 输出，找到所有 asset_required 的 member，
    根据 frame 坐标从 cover 图上裁切，缩放到 96x96 保存。
    裁切后的路径写回 component spec 的 member.asset_path 字段。
    """
    from PIL import Image

    enriched = json.loads(Path(args.enriched_json).read_text(encoding="utf-8"))
    design = json.loads(Path(args.design_json).read_text(encoding="utf-8"))
    cover = Image.open(args.cover_image)

    ab_frame = design["artboard"]["frame"]
    scale_x = cover.width / ab_frame["width"]
    scale_y = cover.height / ab_frame["height"]

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cropped_count = 0
    results = []

    for comp in enriched.get("components", []):
        for member in comp.get("members", []):
            if not member.get("asset_required"):
                continue

            frame = member.get("frame")
            if not frame:
                continue

            x = int(frame["left"] * scale_x)
            y = int(frame["top"] * scale_y)
            w = int(frame["width"] * scale_x)
            h = int(frame["height"] * scale_y)

            if w <= 0 or h <= 0:
                continue
            x = max(0, min(x, cover.width - 1))
            y = max(0, min(y, cover.height - 1))
            w = min(w, cover.width - x)
            h = min(h, cover.height - y)

            region = cover.crop((x, y, x + w, y + h))
            icon = region.resize((96, 96), Image.LANCZOS)

            mid = member["id"].replace(":", "_").replace(";", "_")
            filename = f"{mid}.png"
            icon.save(out_dir / filename)

            member["asset_path"] = str(out_dir / filename)
            cropped_count += 1
            results.append({
                "id": member["id"],
                "name": member.get("name"),
                "file": filename,
            })

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(enriched, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print(json.dumps({
        "ok": True,
        "cropped": cropped_count,
        "files": results,
    }, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(description="ICP Stage 1 bind")
    sub = parser.add_subparsers(dest="command")

    p_prepare = sub.add_parser("prepare", help="生成节点摘要")
    p_prepare.add_argument("--design-json", required=True, help="蓝湖 sketch JSON 路径")
    p_prepare.add_argument("--ui-desc", help="UI 描述(iole 传入，供模型分组参考)")
    p_prepare.add_argument("--output", help="输出路径(不指定则打印到 stdout)")

    p_bind = sub.add_parser("bind", help="绑定分组到设计数据")
    p_bind.add_argument("--design-json", required=True, help="蓝湖 sketch JSON 路径")
    p_bind.add_argument("--grouping", required=True, help="模型分组结果 JSON 路径")
    p_bind.add_argument("--output", help="输出路径")

    p_clean = sub.add_parser("clean", help="删除系统组件")
    p_clean.add_argument("--bound-json", required=True, help="bind 输出的 JSON 路径")
    p_clean.add_argument("--output", help="输出路径")

    p_enrich = sub.add_parser("enrich", help="合并切片+标记缺失资源")
    p_enrich.add_argument("--bound-json", required=True, help="clean 输出的 JSON 路径")
    p_enrich.add_argument("--slices-json", required=True, help="lanhu_get_design_slices 结果 JSON")
    p_enrich.add_argument("--design-json", help="蓝湖 sketch JSON(用于判断子节点结构)")
    p_enrich.add_argument("--output", help="输出路径")

    p_crop = sub.add_parser("crop", help="裁切 asset_required 节点图标")
    p_crop.add_argument("--enriched-json", required=True, help="enrich 输出的 JSON 路径")
    p_crop.add_argument("--design-json", required=True, help="蓝湖 sketch JSON")
    p_crop.add_argument("--cover-image", required=True, help="整页截图路径(PNG)")
    p_crop.add_argument("--output-dir", required=True, help="裁切图输出目录")
    p_crop.add_argument("--output", help="更新后的 JSON 输出路径")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1

    cmds = {"prepare": cmd_prepare, "bind": cmd_bind, "clean": cmd_clean, "enrich": cmd_enrich, "crop": cmd_crop}
    return cmds[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
