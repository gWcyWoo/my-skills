#!/usr/bin/env python3
"""Normalize a Google Sheets task table into the canonical ICPS row shape.

The model fetches raw sheet values through the Google Sheets MCP; this script
does the deterministic column -> field mapping. Headers are matched by NAME,
not position, so reordering columns in the sheet is harmless and a renamed or
dropped column halts loudly instead of silently shifting data.

Canonical row (iole-item.row):

  {"row_id", "title",
   "payload": {route, design_urls[], ui_description, interaction_description,
               ut, it, e2e, api_description, prn_id},
   "roles": {"<role>": {status, pr, reviews, last_error, lease_token, lease_until}}}

row_id is "r<N>" with N the 1-based spreadsheet row number, so every row id
points back at the sheet row it came from.
"""
import argparse
import json
import sys
from pathlib import Path

HEADER_MAP = {
    "标题": "title",
    "Route": "route",
    "设计稿地址": "design_urls",
    "UI补充描述": "ui_description",
    "交互描述": "interaction_description",
    "UT": "ut",
    "IT": "it",
    "E2E": "e2e",
    "接口描述": "api_description",
    "PRN ID": "prn_id",
}
ROLES = ("frontend", "backend")
ROLE_FIELDS = ("status", "pr", "reviews", "last_error", "lease_token", "lease_until")
PAYLOAD_FIELDS = ("route", "design_urls", "ui_description", "interaction_description",
                  "ut", "it", "e2e", "api_description", "prn_id")


def emit(ok, payload, code=0):
    print(json.dumps({"ok": ok, **payload}, ensure_ascii=False, sort_keys=True))
    return code


def extract_values(doc):
    """Accept the MCP envelope, a bare {values:[...]}, or a bare list of rows."""
    if isinstance(doc, list):
        return doc
    if isinstance(doc, dict):
        if "values" in doc:
            return doc["values"]
        res = doc.get("result", doc)
        if isinstance(res, dict):
            if "values" in res:
                return res["values"]
            ranges = res.get("valueRanges") or []
            if ranges and isinstance(ranges[0], dict) and "values" in ranges[0]:
                return ranges[0]["values"]
    return None


def norm(v):
    if v is None:
        return ""
    return v.strip() if isinstance(v, str) else str(v).strip()


def build_index(header):
    idx = {}
    for i, raw in enumerate(header):
        key = norm(raw)
        if not key:
            continue
        if key in HEADER_MAP:
            idx.setdefault(HEADER_MAP[key], i)
        for role in ROLES:
            for field in ROLE_FIELDS:
                if key == f"{role} {field}":
                    idx.setdefault(f"{role}.{field}", i)
    return idx


def required_keys():
    keys = list(HEADER_MAP.values())
    for role in ROLES:
        keys.extend(f"{role}.{f}" for f in ROLE_FIELDS)
    return keys


def cell(row, idx, key):
    i = idx.get(key)
    if i is None or i >= len(row):
        return ""
    return norm(row[i])


def split_urls(raw):
    """Design cells hold 0..N urls, newline separated; '无' and prose are dropped."""
    out = []
    for line in raw.replace("\r", "\n").split("\n"):
        line = line.strip()
        if line.startswith("http://") or line.startswith("https://"):
            out.append(line)
    return out


def normalize(values):
    if not values:
        return None, [{"code": "empty_sheet", "where": "values"}]
    idx = build_index(values[0])
    missing = [k for k in required_keys() if k not in idx]
    if missing:
        return None, [{"code": "missing_column", "where": k} for k in missing]

    rows, errors, by_title = [], [], {}
    for n, raw in enumerate(values[1:], start=2):
        title = cell(raw, idx, "title")
        if not title:
            continue  # spacer / trailing blank rows carry no task
        row_id = f"r{n}"
        if title in by_title:
            errors.append({"code": "duplicate_title", "where": row_id,
                           "detail": f"{title} already at {by_title[title]}"})
        by_title[title] = row_id

        payload = {}
        for field in PAYLOAD_FIELDS:
            v = cell(raw, idx, field)
            payload[field] = split_urls(v) if field == "design_urls" else v

        roles = {}
        for role in ROLES:
            roles[role] = {f: (cell(raw, idx, f"{role}.{f}") or None) for f in ROLE_FIELDS}

        rows.append({"row_id": row_id, "title": title, "payload": payload, "roles": roles})

    return {"schema": "iole-item.sheet", "rows": rows}, errors


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sheet_normalize.py")
    ap.add_argument("--values", required=True,
                    help="JSON file holding the raw MCP get_sheet_data result")
    ap.add_argument("--out", required=True, help="canonical backend JSON to write")
    args = ap.parse_args(argv)

    doc = json.loads(Path(args.values).read_text(encoding="utf-8"))
    values = extract_values(doc)
    if values is None:
        return emit(False, {"errors": [{"code": "no_values", "where": args.values}]}, 1)

    backend, errors = normalize(values)
    if errors:
        return emit(False, {"errors": errors}, 1)

    Path(args.out).write_text(
        json.dumps(backend, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
        encoding="utf-8")
    return emit(True, {"out": args.out, "rows": len(backend["rows"])})


if __name__ == "__main__":
    sys.exit(main())
