#!/usr/bin/env python3
"""ICPS 写回 — canonical 角色单元格 → Google Sheets 更新载荷。

分工同「归一」:列位解析与 A1 range 拼装是确定性变换,归脚本;
真正的 `mcp__google_sheets__batch_update_cells` 调用是模型 I/O,归模型。

用法:
  sheet_writeback.py --values <raw.json> --link <sheet.json>
                     --spreadsheet-id <doc_id> --sheet <名>
                     --role <role> --row-ids r2,r8

输出 mcp_args 可直接传给 mcp__google_sheets__batch_update_cells。
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sheet_normalize import (ROLE_FIELDS, api_error, build_index, emit,
                             extract_values)  # noqa: E402


def a1_col(index):
    """0 → A, 25 → Z, 26 → AA。"""
    out = ""
    n = index + 1
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(ord("A") + rem) + out
    return out


def cell_text(value):
    """canonical 的 null 表示该格应被清空,不是字面 'None'。"""
    return "" if value is None else str(value)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sheet_writeback.py")
    ap.add_argument("--values", required=True, help="原始 values JSON(取表头列位)")
    ap.add_argument("--link", required=True, help="canonical sheet.json(取当前值)")
    ap.add_argument("--spreadsheet-id", required=True, help="Google Spreadsheet ID")
    ap.add_argument("--sheet", required=True, help="工作表名,如 Sheet1")
    ap.add_argument("--role", required=True)
    ap.add_argument("--row-ids", required=True, help="逗号分隔,如 r2,r8")
    args = ap.parse_args(argv)

    raw = json.loads(Path(args.values).read_text(encoding="utf-8"))
    err = api_error(raw)
    if err is not None:
        code = "doc_not_found" if str(err.get("code")) == "404" else "source_error"
        return emit(False, {"errors": [{"code": code, "where": args.values,
                                        "detail": err}]}, 1)
    values = extract_values(raw)
    if not values:
        return emit(False, {"errors": [{"code": "no_values", "where": args.values}]}, 1)

    idx = build_index(values[0])
    missing = [f for f in ROLE_FIELDS if f"{args.role}.{f}" not in idx]
    if missing:
        return emit(False, {"errors": [{"code": "missing_column",
                                        "where": f"{args.role} {f}"} for f in missing]}, 1)

    backend = json.loads(Path(args.link).read_text(encoding="utf-8"))
    by_id = {r["row_id"]: r for r in backend.get("rows", [])}

    want = [rid.strip() for rid in args.row_ids.split(",") if rid.strip()]
    unknown = [rid for rid in want if rid not in by_id]
    if unknown:
        return emit(False, {"errors": [{"code": "unknown_row", "where": rid}
                                       for rid in unknown]}, 1)

    updates = []
    ranges = {}
    for rid in want:
        row = by_id[rid]
        row_index = int(rid[1:])  # row_id 始终指回原表格行号
        cells = row.get("roles", {}).get(args.role, {})
        for field in ROLE_FIELDS:
            cell_range = f"{a1_col(idx[f'{args.role}.{field}'])}{row_index}"
            value = cell_text(cells.get(field))
            updates.append({
                "row_id": rid,
                "field": field,
                "range": f"{args.sheet}!{cell_range}",
                "value": value,
            })
            ranges[cell_range] = [[value]]

    mcp_args = {"spreadsheet_id": args.spreadsheet_id,
                "sheet": args.sheet, "ranges": ranges}
    return emit(True, {"sheet": args.sheet, "role": args.role,
                       "count": len(updates), "updates": updates,
                       "mcp_args": mcp_args})


if __name__ == "__main__":
    raise SystemExit(main())
