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
import re
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


def _documents(doc):
    """Yield JSON payloads nested in Codex CallToolResult envelopes."""
    stack = [doc]
    while stack:
        candidate = stack.pop()
        yield candidate
        if not isinstance(candidate, dict):
            continue
        for key in ("structuredContent", "result"):
            nested = candidate.get(key)
            if isinstance(nested, dict):
                stack.append(nested)
        for block in candidate.get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            try:
                stack.append(json.loads(block.get("text", "")))
            except (json.JSONDecodeError, TypeError):
                continue


def extract_values(doc):
    """Accept Codex CallToolResult, legacy MCP envelopes, or bare values."""
    if isinstance(doc, list):
        return doc
    for candidate in _documents(doc):
        if isinstance(candidate, list):
            return candidate
        if not isinstance(candidate, dict):
            continue
        if "values" in candidate:
            return candidate["values"]
        ranges = candidate.get("valueRanges") or []
        if ranges and isinstance(ranges[0], dict) and "values" in ranges[0]:
            return ranges[0]["values"]
    return None


def api_error(doc):
    """Spot API errors and Codex CallToolResult `isError` envelopes."""
    for candidate in _documents(doc):
        if isinstance(candidate, dict) and isinstance(candidate.get("error"), dict):
            return candidate["error"]
    if isinstance(doc, dict) and doc.get("isError"):
        detail = "\n".join(
            str(block.get("text", "")) for block in doc.get("content") or []
            if isinstance(block, dict) and block.get("type") == "text"
        )
        match = re.search(r"\bHttpError\s+(\d{3})\b", detail)
        return {"code": int(match.group(1)) if match else "mcp_error",
                "message": detail}
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
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--values", help="JSON file holding raw mcp__google_sheets__get_sheet_data output")
    grp.add_argument("--stdin", action="store_true",
                     help="read raw MCP JSON from stdin instead of a file")
    ap.add_argument("--save-raw", metavar="PATH",
                    help="persist raw input to this path (useful with --stdin)")
    ap.add_argument("--out", required=True, help="canonical backend JSON to write")
    args = ap.parse_args(argv)

    if args.stdin:
        raw_text = sys.stdin.read()
        doc = json.loads(raw_text)
        if args.save_raw:
            Path(args.save_raw).parent.mkdir(parents=True, exist_ok=True)
            Path(args.save_raw).write_text(raw_text, encoding="utf-8")
    else:
        doc = json.loads(Path(args.values).read_text(encoding="utf-8"))

    # 取数失败要当场直呼原因:doc_id 打错(404) 与「文件里没有 values」不是一回事。
    err = api_error(doc)
    if err is not None:
        code = "doc_not_found" if str(err.get("code")) == "404" else "source_error"
        return emit(False, {"errors": [{"code": code, "where": args.values,
                                        "detail": err}]}, 1)

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
