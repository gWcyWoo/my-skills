#!/usr/bin/env python3
"""ICP Stage 1 取数入口 — 设计稿引用按地址前缀分流到平台适配器。

    python3 design_fetch.py check --ref "<设计稿引用>"
    python3 design_fetch.py fetch --ref "<设计稿引用>" --out-dir <dir>

check 只做离线格式校验(不联网)，供 iole 在领取后、派发 ICP 前提前报错；
fetch 交给适配器产出 INPUT.md 契约四件套。stdout 只有一行 JSON。

新增平台只加 DESIGNS 一行 + 一个适配器模块(parse_ref / fetch)。
"""

import argparse
import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 登记表:地址前缀 → (平台名, 适配器模块)。
DESIGNS = [
    ("https://lanhuapp.com", "lanhu", "lanhu_fetch"),
    ("https://47.84.143.250.sslip.io", "selfhost", "selfhost_fetch"),
]


def emit(payload, code):
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return code


def emit_error(err_type, detail, code=1):
    return emit({"ok": False, "errors": [{"type": err_type, "detail": detail}]}, code)


def resolve(ref):
    """首个匹配的前缀 → (平台名, 适配器, base)；否则 None。

    前缀后紧跟的字符不能还属于主机名，否则 lanhuapp.com.evil.com 也会命中。
    """
    for base, name, module in DESIGNS:
        if ref.startswith(base):
            nxt = ref[len(base):len(base) + 1]
            if nxt and (nxt.isascii() and nxt.isalnum() or nxt in ".-"):
                continue
            return name, importlib.import_module(module), base
    return None


def cmd_check(args):
    ref = args.ref.strip()
    hit = resolve(ref)
    if hit is None:
        return emit_error("unknown_design", f"无法识别的设计稿引用: {ref}")
    name, adapter, base = hit
    try:
        parsed = adapter.parse_ref(ref, base)
    except ValueError as e:
        return emit_error("bad_ref", str(e))
    return emit({"ok": True, "design": name, **parsed}, 0)


def cmd_fetch(args, http_get):
    ref = args.ref.strip()
    hit = resolve(ref)
    if hit is None:
        return emit_error("unknown_design", f"无法识别的设计稿引用: {ref}")
    _, adapter, base = hit
    try:
        adapter.parse_ref(ref, base)
    except ValueError as e:
        return emit_error("bad_ref", str(e))
    # 适配器自己输出一行 summary JSON
    return adapter.fetch(ref, base, Path(args.out_dir), cookie=args.cookie,
                         skip_cover=args.skip_cover, http_get=http_get)


def main(argv=None, http_get=None):
    ap = argparse.ArgumentParser(description="设计稿引用 → 平台适配器")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ck = sub.add_parser("check", help="离线校验引用格式")
    ck.add_argument("--ref", required=True)
    ck.set_defaults(fn=cmd_check)
    ft = sub.add_parser("fetch", help="取数 → design.json/slices.json/cover.png/assets")
    ft.add_argument("--ref", required=True)
    ft.add_argument("--out-dir", required=True)
    ft.add_argument("--cookie", default=None, help="覆盖 cookie(否则走适配器的环境变量)")
    ft.add_argument("--skip-cover", action="store_true", help="不下载整页截图")
    ft.set_defaults(fn=lambda a: cmd_fetch(a, http_get))
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
