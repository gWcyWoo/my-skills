#!/usr/bin/env python3
"""ICP Stage 3 — validate: 验证代码生成产物是否匹配蓝图意图。

子命令:
  check-codegen   验证生成代码的文案覆盖、DTO 覆盖
"""

import argparse
import json
import re
import sys
from pathlib import Path

PLATFORMS = ["android-views", "compose", "flutter", "swiftui", "uikit"]


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
    stripped = re.sub(r'"""[\s\S]*?"""', '', source)
    doubles = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', stripped)
    if platform == "flutter":
        stripped = re.sub(r"'''[\s\S]*?'''", '', stripped)
        stripped = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', '', stripped)
        doubles += re.findall(r"'([^'\\]*(?:\\.[^'\\]*)*)'", stripped)
    return doubles


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
        code_strings = _extract_string_literals(full_source, platform)

        matched = 0
        missing = []
        for bt in bp_texts:
            if bt[:20] in full_source:
                matched += 1
            elif any(cs in bt for cs in code_strings if len(cs) >= 6):
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
    apis = contract.get("apis", [])
    for api in apis:
        resolved = api.get("resolved")
        if not resolved:
            continue
        resp = resolved.get("response")
        if not isinstance(resp, dict):
            continue
        hint = api.get("semantic_hint") or api.get("endpoint") or "?"
        field_pairs = _extract_response_fields(resp)
        missing_fields = list(dict.fromkeys(
            camel for snake, camel in field_pairs
            if len(snake) >= 3 and snake not in source and camel not in source
        ))
        if missing_fields:
            errors.append({
                "type": "missing_dto_field",
                "api": hint,
                "missing": missing_fields,
                "detail": "DTO 缺少 resolved.response 中的字段",
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
