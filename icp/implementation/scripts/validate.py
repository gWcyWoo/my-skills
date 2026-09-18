#!/usr/bin/env python3
"""ICP Stage 3 — validate: 验证代码生成产物是否匹配蓝图意图。

子命令:
  check-codegen   验证生成代码的文案覆盖、DTO 覆盖、资产覆盖、绝对定位
"""

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

PLATFORMS = ["android-views", "compose", "flutter", "swiftui", "uikit"]

_OFFSET_PATTERNS = {
    "compose": (
        re.compile(r'\.(?:offset|absoluteOffset)\s*[({]'),
        "*.kt",
        re.compile(r'\bBoxWithConstraints\b'),
        re.compile(r'\bmaxWidth\b|\bmaxHeight\b'),
    ),
    "flutter": (
        re.compile(r'\b(?:Animated)?Positioned(?:Directional|Transition)?(?:\.(?:directional|fromRect|fromRelativeRect))?\s*\(|\bTransform\.translate\s*\('),
        "*.dart",
        re.compile(r'\bLayoutBuilder\b'),
        re.compile(r'\bconstraints\.\w'),
    ),
    "swiftui": (
        re.compile(r'\.(?:offset|position)\s*\('),
        "*.swift",
        re.compile(r'\bGeometryReader\b'),
        re.compile(r'\bgeometry\b'),
    ),
}
_COMMENT_STRIP_RE = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|/\*[\s\S]*?\*/|//[^\n]*')


def _snake_to_camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _extract_response_fields(schema):
    """递归提取 resolved.response 的所有字段名,返回 (snake_case, camelCase) 对。"""
    fields = []
    for key, val in schema.items():
        fields.append((key, _snake_to_camel(key)))
        if isinstance(val, dict):
            fields.extend(_extract_response_fields(val))
        elif isinstance(val, list) and val and isinstance(val[0], dict):
            fields.extend(_extract_response_fields(val[0]))
    return fields


_CODE_EXTS = {
    ".kt", ".java", ".swift", ".m", ".h", ".dart",
}

_RESOURCE_EXTS = {".xml", ".storyboard", ".xib", ".strings"}


def _collect_files(gen_dir: Path, exts: set) -> str:
    parts = []
    for f in sorted(gen_dir.rglob("*")):
        if not f.is_file() or f.suffix not in exts:
            continue
        try:
            parts.append(f.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            print(f"warning: skipped {f} (not UTF-8)", file=sys.stderr)
    return "\n".join(parts)


def _extract_string_literals(source: str, platform: str = "") -> list[str]:
    """从源码中提取字符串字面量。单引号仅对 flutter(Dart) 启用。"""
    results = []
    for m in re.finditer(r'"""([\s\S]*?)"""', source):
        results.append(m.group(1))
    stripped = re.sub(r'"""[\s\S]*?"""', '', source)
    if platform == "flutter":
        for m in re.finditer(r"'''([\s\S]*?)'''", stripped):
            results.append(m.group(1))
        stripped = re.sub(r"'''[\s\S]*?'''", '', stripped)
        for m in re.finditer(r'"([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\'', stripped):
            results.append(m.group(1) if m.group(1) is not None else m.group(2))
    else:
        results.extend(re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', stripped))
    return results


def cmd_check_codegen(args):
    blueprint = json.loads(Path(args.blueprint).read_text(encoding="utf-8"))
    contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
    gen_dir = Path(args.gen_dir)
    platform = args.platform

    if not gen_dir.exists():
        print(json.dumps({"ok": False, "errors": [
            {"type": "missing_gen_dir", "path": str(gen_dir)}
        ]}, ensure_ascii=False))
        sys.exit(1)

    source = _collect_files(gen_dir, _CODE_EXTS)
    resource_source = _collect_files(gen_dir, _RESOURCE_EXTS)
    full_source = source + "\n" + resource_source
    if not source.strip():
        print(json.dumps({"ok": False, "errors": [
            {"type": "empty_source", "path": str(gen_dir)}
        ]}, ensure_ascii=False))
        sys.exit(1)

    errors = []
    warnings = []

    bp_comps = blueprint.get("components", [])

    # --- 文案覆盖率 ---
    bp_texts = []
    for comp in bp_comps:
        for t in comp.get("texts", []):
            v = t.get("value", "").strip()
            if v and len(v) >= 2:
                bp_texts.append(v)

    if bp_texts:
        clean_source = _COMMENT_STRIP_RE.sub(
            lambda m: m.group(0) if m.group(0)[0] in ('"', "'") else ' ',
            full_source)
        code_strings = [unicodedata.normalize("NFC", value)
                        for value in _extract_string_literals(clean_source, platform)]
        normalized_resources = unicodedata.normalize("NFC", resource_source)

        matched = 0
        missing = []
        for bt in bp_texts:
            normalized_text = unicodedata.normalize("NFC", bt)
            if any(normalized_text in cs for cs in code_strings):
                matched += 1
            elif any(cs in normalized_text for cs in code_strings if len(cs) >= 6):
                matched += 1
            elif normalized_text in normalized_resources:
                matched += 1
            else:
                missing.append(bt[:60])

        coverage = matched / len(bp_texts)
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

    # --- DTO 覆盖 resolved.response ---
    dto_source = _COMMENT_STRIP_RE.sub(lambda m: m.group(0) if m.group(0)[0] in ('"', "'") else ' ', source)

    def _has_field(name: str) -> bool:
        return bool(re.search(r'\b' + re.escape(name) + r'\b', dto_source))

    apis = contract.get("apis", [])
    for api in apis:
        resolved = api.get("resolved")
        if not resolved:
            continue
        resp = resolved.get("response")
        if isinstance(resp, list) and resp and isinstance(resp[0], dict):
            resp = resp[0]
        elif not isinstance(resp, dict):
            continue
        hint = api.get("semantic_hint") or api.get("endpoint") or "?"
        field_pairs = _extract_response_fields(resp)
        missing_fields = list(dict.fromkeys(
            camel for snake, camel in field_pairs
            if len(snake) >= 3 and not _has_field(snake) and not _has_field(camel)
        ))
        if missing_fields:
            errors.append({
                "type": "missing_dto_field",
                "api": hint,
                "missing": missing_fields,
                "detail": "DTO 缺少 resolved.response 中的字段",
            })

    # --- 资产覆盖 ---
    bp_assets_with_file = []
    for comp in bp_comps:
        for a in comp.get("assets", []):
            rn = a.get("resource_name")
            if rn and a.get("file"):
                bp_assets_with_file.append(rn)

    if bp_assets_with_file:
        missing_assets = [
            rn for rn in bp_assets_with_file
            if not re.search(r'\b' + re.escape(rn) + r'\b', dto_source + "\n" + resource_source)
        ]
        if missing_assets:
            errors.append({
                "type": "missing_asset_ref",
                "missing_count": len(missing_assets),
                "missing": missing_assets[:10],
                "detail": "blueprint 的 assets 有导出文件但代码未引用 resource_name",
            })

    # --- extract_shared affected 引用检查 ---
    for comp in contract.get("components", []):
        if comp.get("type") != "extract_shared":
            continue
        affected = comp.get("affected") or []
        comp_name = comp.get("name", "?")
        for af in affected:
            sp = af.get("source_path")
            if not sp:
                continue
            af_name = af.get("name") or Path(sp).stem
            if af_name and not re.search(r'\b' + re.escape(af_name) + r'\b', source):
                warnings.append({
                    "type": "affected_not_referenced",
                    "component": comp_name,
                    "affected_source": sp,
                    "detail": "extract_shared 的 affected 组件未在生成代码中被引用",
                })

    # --- 绝对定位检测 ---
    offset_cfg = _OFFSET_PATTERNS.get(platform)
    if offset_cfg:
        offset_re, glob, scope_re, proportion_re = offset_cfg
        hits = []
        for f in sorted(gen_dir.rglob(glob)):
            if not f.is_file():
                continue
            try:
                raw = f.read_text(encoding="utf-8").split("\n")
            except UnicodeDecodeError:
                continue
            stripped = _COMMENT_STRIP_RE.sub(
                lambda m: re.sub(r'[^\n]', ' ', m.group(0)),
                "\n".join(raw))
            if scope_re.search(stripped):
                continue
            lines = stripped.split("\n")
            for i, line in enumerate(lines):
                if not offset_re.search(line):
                    continue
                ctx = " ".join(lines[i:i+5])
                if proportion_re.search(ctx):
                    continue
                hits.append(f"{f.relative_to(gen_dir)}:{i+1}")
        if hits:
            errors.append({
                "type": "absolute_positioning",
                "count": len(hits),
                "sites": hits[:10],
                "detail": "代码使用绝对定位，应改用平台布局原语",
            })

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
    p_cg.add_argument("--platform", required=True,
                       choices=PLATFORMS,
                       help="目标平台")

    args = parser.parse_args()
    if args.command == "check-codegen":
        cmd_check_codegen(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
