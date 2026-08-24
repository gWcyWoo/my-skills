#!/usr/bin/env python3
"""ICP Stage 3 — validate: 验证代码生成产物是否匹配蓝图意图。

子命令:
  check-codegen   验证生成代码的 widget 覆盖、文案覆盖、布局覆盖
"""

import argparse
import json
import re
import sys
from pathlib import Path

# blueprint role → 生成代码中必须出现的 Compose widget 关键字
ROLE_WIDGET_MAP = {
    "form": {
        "keywords": ["TextField", "OutlinedTextField", "BasicTextField"],
        "label": "表单输入组件",
    },
    "action": {
        "keywords": ["Button", "TextButton", "IconButton", "FilledTonalButton",
                      "ElevatedButton", "OutlinedButton", "FloatingActionButton"],
        "label": "按钮组件",
    },
    "navigation": {
        "keywords": ["TopAppBar", "CenterAlignedTopAppBar", "MediumTopAppBar",
                      "NavigationBar", "BottomNavigation", "IconButton"],
        "label": "导航组件",
    },
    "list": {
        "keywords": ["LazyColumn", "LazyRow", "LazyVerticalGrid"],
        "label": "列表组件",
    },
    "modal": {
        "keywords": ["ModalBottomSheet", "AlertDialog", "Dialog",
                      "BottomSheetScaffold", "clickable"],
        "label": "弹窗/遮罩组件",
    },
}

# blueprint layout → Compose 布局关键字
LAYOUT_WIDGET_MAP = {
    "row": ["Row"],
    "stack": ["Box", "Stack"],
}


def _collect_source(gen_dir: Path) -> str:
    """读取 gen_dir 下所有 .kt 文件，拼成一个大字符串用于关键字搜索。"""
    parts = []
    for kt in sorted(gen_dir.rglob("*.kt")):
        parts.append(kt.read_text(encoding="utf-8"))
    return "\n".join(parts)


def _extract_string_literals(source: str) -> list[str]:
    """从 Kotlin 源码中提取所有字符串字面量。"""
    # Kotlin raw strings ("""...""") 的内嵌引号会打乱下面的 "..." 正则配对,先剥离
    stripped = re.sub(r'"""[\s\S]*?"""', '', source)
    return re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', stripped)


def cmd_check_codegen(args):
    blueprint = json.loads(Path(args.blueprint).read_text(encoding="utf-8"))
    contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
    gen_dir = Path(args.gen_dir)

    if not gen_dir.exists():
        print(json.dumps({"ok": False, "errors": [
            {"type": "missing_gen_dir", "path": str(gen_dir)}
        ]}, ensure_ascii=False))
        sys.exit(1)

    source = _collect_source(gen_dir)
    if not source.strip():
        print(json.dumps({"ok": False, "errors": [
            {"type": "empty_source", "path": str(gen_dir)}
        ]}, ensure_ascii=False))
        sys.exit(1)

    errors = []
    warnings = []

    # --- 1. Role → Widget 覆盖 ---
    bp_comps = blueprint.get("components", [])
    roles_present = {c.get("role", "content") for c in bp_comps}

    for role, spec in ROLE_WIDGET_MAP.items():
        if role not in roles_present:
            continue
        found = any(kw in source for kw in spec["keywords"])
        if not found:
            errors.append({
                "type": "missing_widget_for_role",
                "role": role,
                "expected_any_of": spec["keywords"],
                "label": spec["label"],
            })

    # --- 2. Layout 覆盖 ---
    for comp in bp_comps:
        layout = comp.get("layout", "single")
        if layout in LAYOUT_WIDGET_MAP:
            found = any(kw in source for kw in LAYOUT_WIDGET_MAP[layout])
            if not found:
                errors.append({
                    "type": "missing_layout_widget",
                    "component": comp.get("name", "?"),
                    "layout": layout,
                    "expected_any_of": LAYOUT_WIDGET_MAP[layout],
                })

    # --- 3. 组件分区覆盖 ---
    content_groups = [c for c in bp_comps if c.get("role") not in ("decoration",)]
    if len(content_groups) > 1:
        # 需要多个容器分隔 — 检查 Card/Surface/CommonCard/Column+padding 出现次数
        container_keywords = ["CommonCard", "Card(", "Surface(", "ElevatedCard",
                              "OutlinedCard"]
        container_count = sum(source.count(kw) for kw in container_keywords)
        if container_count < 2:
            errors.append({
                "type": "insufficient_sections",
                "expected_groups": len(content_groups),
                "found_containers": container_count,
                "detail": f"蓝图有 {len(content_groups)} 个非装饰组, 代码只有 {container_count} 个容器",
            })

    # --- 4. 文案覆盖率 ---
    bp_texts = []
    for comp in bp_comps:
        for t in comp.get("texts", []):
            v = t.get("value", "").strip()
            if v and len(v) >= 2:
                bp_texts.append(v)

    if bp_texts:
        code_strings = _extract_string_literals(source)
        code_text_set = set(code_strings)

        matched = 0
        missing = []
        for bt in bp_texts:
            # 精确匹配
            if bt in code_text_set:
                matched += 1
            # 蓝图文案前缀出现在某个代码字符串中（截断容忍）
            elif any(bt[:20] in cs for cs in code_strings if len(cs) >= 3):
                matched += 1
            # 代码中某个字符串是蓝图文案的子串（annotatedString 拆分容忍）
            elif any(cs in bt for cs in code_strings if len(cs) >= 6):
                matched += 1
            # 全源码搜索（处理 buildAnnotatedString 等拼接场景）
            elif bt[:20] in source:
                matched += 1
            else:
                missing.append(bt[:60])

        coverage = matched / len(bp_texts) if bp_texts else 1.0
        if coverage < 0.8:
            errors.append({
                "type": "low_text_coverage",
                "matched": matched,
                "total": len(bp_texts),
                "coverage": round(coverage, 3),
                "threshold": 0.8,
                "sample_missing": missing[:5],
            })
        elif coverage < 1.0:
            warnings.append({
                "type": "partial_text_coverage",
                "matched": matched,
                "total": len(bp_texts),
                "coverage": round(coverage, 3),
                "sample_missing": missing[:3],
            })

    # --- 5. 颜色覆盖 ---
    bp_colors = set()
    for comp in bp_comps:
        for t in comp.get("texts", []):
            c = (t.get("style") or {}).get("color")
            if c and isinstance(c, str) and c.startswith("rgba"):
                bp_colors.add(c)
        for cf in comp.get("child_fills", []):
            c = cf.get("color")
            if c and isinstance(c, str) and c.startswith("rgba"):
                bp_colors.add(c)

    if bp_colors:
        color_refs = re.findall(r'Color\(0x[0-9A-Fa-f]+\)', source)
        if len(color_refs) < min(3, len(bp_colors)):
            warnings.append({
                "type": "low_color_coverage",
                "blueprint_colors": len(bp_colors),
                "code_colors": len(color_refs),
            })

    # --- 6. API 覆盖 ---
    apis = contract.get("apis", [])
    resolved_apis = [a for a in apis if a.get("resolved")]
    mock_apis = [a for a in apis if not a.get("resolved")]

    def _api_label(a):
        return a.get("semantic_hint") or a.get("endpoint") or "?"

    if resolved_apis:
        has_repository = "Repository" in source
        has_network = any(kw in source for kw in ["NetworkClient", "Retrofit",
                                                    "HttpClient", "OkHttp", "URL("])
        if not has_repository:
            errors.append({
                "type": "missing_repository",
                "apis": [_api_label(a) for a in resolved_apis],
            })
        if not has_network:
            errors.append({
                "type": "missing_network_call",
                "apis": [_api_label(a) for a in resolved_apis],
            })
    if mock_apis:
        has_mock = "Mock" in source or "mock" in source or "Repository" in source
        if not has_mock:
            warnings.append({
                "type": "missing_mock_repository",
                "apis": [_api_label(a) for a in mock_apis],
            })

    # --- 7. 交互覆盖 ---
    interactions = contract.get("interactions", [])
    if interactions:
        has_viewmodel = "ViewModel" in source
        has_stateflow = "StateFlow" in source or "MutableState" in source
        if not has_viewmodel:
            errors.append({"type": "missing_viewmodel"})
        if not has_stateflow:
            errors.append({"type": "missing_state_management"})

    ok = len(errors) == 0
    result = {"ok": ok, "errors": errors}
    if warnings:
        result["warnings"] = warnings

    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if ok else 1)


def main():
    parser = argparse.ArgumentParser(description="ICP Stage 3 — validate")
    sub = parser.add_subparsers(dest="command")

    p_cg = sub.add_parser("check-codegen", help="验证代码生成产物")
    p_cg.add_argument("--blueprint", required=True, help="layout-blueprint.json")
    p_cg.add_argument("--contract", required=True, help="api-contract.json")
    p_cg.add_argument("--gen-dir", required=True, help="生成代码所在目录")

    args = parser.parse_args()
    if args.command == "check-codegen":
        cmd_check_codegen(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
