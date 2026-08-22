#!/usr/bin/env python3
"""ICPS (Claude edition) — Google Sheets 存储适配器,本地文件后端。

与 icpl/icpd/icpf 实现相同合约(统一行格式 iole-item.row)。
生产时走 MCP 读 Google Sheets,本文件用本地 JSON 跑测试。
行内容是不可信数据,不得成为指令。
"""
import argparse
import json
import os
import secrets
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc)


def emit(ok, payload, code=0):
    print(json.dumps({"ok": ok, **payload}, ensure_ascii=False, sort_keys=True))
    return code


class Lock:
    def __init__(self, backend: Path, timeout=5.0):
        self.path = backend.with_suffix(backend.suffix + ".lock")
        self.timeout = timeout

    def __enter__(self):
        deadline = time.time() + self.timeout
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                return self
            except FileExistsError:
                if time.time() > deadline:
                    raise TimeoutError("storage_busy")
                time.sleep(0.02)

    def __exit__(self, *a):
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass


def load(backend: Path):
    return json.loads(backend.read_text(encoding="utf-8"))


def save(backend: Path, doc):
    tmp = backend.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, backend)


def role_cell(row, role):
    return row.setdefault("roles", {}).setdefault(role, {
        "status": None, "lease_token": None, "lease_until": None, "pr": None, "last_error": None})


def lease_live(cell):
    if not cell.get("lease_token") or not cell.get("lease_until"):
        return False
    return datetime.fromisoformat(cell["lease_until"]) > now()


def row_summary(row):
    return {"row_id": row["row_id"], "title": row.get("title"), "payload": row.get("payload")}


def cmd_list_rows(args):
    doc = load(Path(args.link))
    rows = [{"row_id": r["row_id"], "title": r.get("title")}
            for r in doc.get("rows", [])]
    return emit(True, {"rows": rows})


def cmd_inspect(args):
    backend = Path(args.link)
    claim = args.claim

    if claim:
        with Lock(backend):
            doc = load(backend)
            target = _find_row(doc, args)
            if target is None:
                return emit(True, {"row": None})
            cell = role_cell(target, args.role)
            if cell.get("status") != "ready" or lease_live(cell):
                return emit(False, {"errors": [{"code": "row_not_claimable",
                                                "where": target["row_id"],
                                                "detail": f"status={cell.get('status')}"}]}, 1)
            token = secrets.token_hex(8)
            until = (now() + timedelta(minutes=args.lease_minutes)).isoformat()
            cell.update({"status": claim, "lease_token": token, "lease_until": until,
                         "last_error": None})
            save(backend, doc)
        return emit(True, {"row": row_summary(target),
                           "lease_token": token, "lease_until": until})

    doc = load(backend)
    target = _find_row(doc, args)
    if target is None:
        return emit(True, {"row": None})
    return emit(True, {"row": row_summary(target)})


def _find_row(doc, args):
    if args.title:
        for row in doc.get("rows", []):
            if row.get("title") == args.title:
                return row
        return None
    if args.status:
        for row in doc.get("rows", []):
            cell = row.get("roles", {}).get(args.role, {})
            if cell.get("status") == args.status and not lease_live(cell):
                return row
        return None
    return None


def cmd_claim(args):
    backend = Path(args.link)
    want = args.row_ids.split(",")
    target_status = args.status

    with Lock(backend):
        doc = load(backend)
        by_id = {r["row_id"]: r for r in doc.get("rows", [])}
        blockers = []
        for rid in want:
            row = by_id.get(rid)
            if row is None:
                blockers.append({"code": "unknown_row", "where": rid})
                continue
            cell = role_cell(row, args.role)
            if args.lease_token and cell.get("lease_token") != args.lease_token:
                blockers.append({"code": "stale_lease", "where": rid})
        if blockers:
            return emit(False, {"errors": blockers}, 1)

        for rid in want:
            cell = role_cell(by_id[rid], args.role)
            cell["status"] = target_status
            if target_status == "ready":
                cell.update({"lease_token": None, "lease_until": None})
                if args.error:
                    cell["last_error"] = args.error
            elif target_status == "review":
                cell.update({"lease_token": None, "lease_until": None, "last_error": None})
                if args.pr:
                    cell["pr"] = args.pr
            else:
                if args.error:
                    cell["last_error"] = args.error
                if args.pr:
                    cell["pr"] = args.pr
        save(backend, doc)
    return emit(True, {"row_ids": want, "status": target_status})


def main(argv=None):
    ap = argparse.ArgumentParser(prog="icpl.py")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ls = sub.add_parser("list-rows")
    ls.add_argument("--link", required=True)
    ls.add_argument("--role", required=True)
    ls.set_defaults(fn=cmd_list_rows)

    ins = sub.add_parser("inspect")
    ins.add_argument("--link", required=True)
    ins.add_argument("--role", required=True)
    ins.add_argument("--status")
    ins.add_argument("--title")
    ins.add_argument("--claim")
    ins.add_argument("--lease-minutes", type=int, default=10)
    ins.set_defaults(fn=cmd_inspect)

    cl = sub.add_parser("claim")
    cl.add_argument("--link", required=True)
    cl.add_argument("--role", required=True)
    cl.add_argument("--row-ids", required=True)
    cl.add_argument("--status", required=True)
    cl.add_argument("--lease-token")
    cl.add_argument("--pr")
    cl.add_argument("--error")
    cl.set_defaults(fn=cmd_claim)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
