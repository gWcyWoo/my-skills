#!/usr/bin/env python3
"""IOLE — 调度器 + 运行台账。

  source   链接 → 存储适配 skill 名(工厂)。树里每个节点各自走一次,
           所以一棵树可以混不同来源的节点。
  record   把节点(含 icpx 取到的行数据)落盘。重录只覆盖数据,不动进度。
  status   计划 + 进度 + 还没录入的子节点。
  next     按叶优先顺序交出下一个待做节点,并标记 doing。
  mark     标记 done / failed / pending(重试)。

台账让长流程可中断续跑:处理一个标记一个,进度不丢、节点不漏、不重做。

iole 不读表(适配 skill 读)、不调蓝湖 API(icp 调)、不解析设计、不写代码。
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "iole.run"
STATUSES = ("pending", "doing", "done", "failed")
LOG_DIR = Path.home() / ".claude" / "logs" / "iole"

# 工厂表:域名模式 → (kind, skill)。新增来源只加一行。
SOURCES = [
    (re.compile(r"docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]+)"), "google-sheet", "icps"),
    (re.compile(r"(?:alidocs\.)?dingtalk\.com/\S*?([A-Za-z0-9_-]{8,})"), "dingtalk-doc", "icpd"),
    (re.compile(r"(?:feishu\.cn|larksuite\.com)/sheets/([A-Za-z0-9_-]+)"), "feishu-sheet", "icpf"),
    (re.compile(r"^((?:/|\.\.?/)\S+\.json)$"), "local-file", "icpl"),
]


def emit(ok, payload, code=0):
    print(json.dumps({"ok": ok, **payload}, ensure_ascii=False, sort_keys=True))
    return code


def _log(cmd, args_dict, output):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entry = {"t": datetime.now(timezone.utc).isoformat(), "cmd": cmd,
             "args": args_dict, "output": output}
    with open(LOG_DIR / f"{day}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


# ------------------------------------------------------------------ 工厂

def resolve_source(link):
    for pattern, kind, skill in SOURCES:
        m = pattern.search(link)
        if m:
            out = {"kind": kind, "skill": skill, "doc_id": m.group(1)}
            gid = re.search(r"[#&?]gid=(\d+)", link)
            if gid:
                out["gid"] = gid.group(1)
            return out
    return None


def cmd_source(args):
    src = resolve_source(args.link)
    if src is None:
        return emit(False, {"errors": [{"code": "unknown_source", "where": args.link,
                                        "detail": "无对应存储适配 skill,须先在 SOURCES 注册"}]}, 1)
    return emit(True, {"source": src})


# ------------------------------------------------------------------ 台账

def load_run(path):
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def save_run(path, run):
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps(run, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
                   encoding="utf-8")
    tmp.replace(Path(path))


def leaf_first(root, children):
    """DFS 后序。回边(目标已在当前路径上)记下并剔出排序——导航图本就有环,
    回边靠 route 名绑定,与实现顺序无关。节点类型无关,异构树同样适用。"""
    order, done, on_path, cycle_edges = [], set(), set(), []
    stack = [(root, iter(children.get(root, [])))]
    on_path.add(root)
    while stack:
        node, kids = stack[-1]
        descended = False
        for kid in kids:
            if kid in done or kid not in children:
                continue
            if kid in on_path:
                if [node, kid] not in cycle_edges:
                    cycle_edges.append([node, kid])
                continue
            on_path.add(kid)
            stack.append((kid, iter(children.get(kid, []))))
            descended = True
            break
        if not descended:
            stack.pop()
            on_path.discard(node)
            done.add(node)
            order.append(node)
    return order, cycle_edges


def child_map(nodes):
    out = {}
    for nid, node in nodes.items():
        kids = []
        for kid in node.get("children") or []:
            if kid != nid and kid in nodes and kid not in kids:
                kids.append(kid)
        out[nid] = kids
    return out


def undiscovered(nodes):
    """被引为子节点、却还没 record 进来的 —— 递归建树尚未完成。"""
    missing = []
    for nid, node in nodes.items():
        for kid in node.get("children") or []:
            if kid not in nodes and {"where": nid, "detail": kid} not in missing:
                missing.append({"where": nid, "detail": kid})
    return missing


def plan(run):
    nodes = run["nodes"]
    order, cycle_edges = leaf_first(run["root"], child_map(nodes))
    return order, cycle_edges, sorted(set(nodes) - set(order))


def cmd_record(args):
    doc = json.loads(Path(args.nodes).read_text(encoding="utf-8"))
    incoming = doc.get("nodes") or {}
    if not incoming:
        return emit(False, {"errors": [{"code": "empty_nodes", "where": args.nodes}]}, 1)

    run = load_run(args.run)
    if run is None:
        root = args.root or doc.get("root")
        if not root:
            return emit(False, {"errors": [{"code": "missing_root",
                                            "detail": "首次 record 须给 --root"}]}, 1)
        run = {"schema": SCHEMA, "link": args.link, "role": args.role, "mr": args.mr,
               "root": root, "nodes": {}, "progress": {}}
    else:
        conflicts = []
        if args.root and args.root != run["root"]:
            conflicts.append(f"root: run={run['root']} vs arg={args.root}")
        if args.link and args.link != run.get("link"):
            conflicts.append(f"link: run={run.get('link')} vs arg={args.link}")
        if args.role and args.role != run.get("role"):
            conflicts.append(f"role: run={run.get('role')} vs arg={args.role}")
        if args.mr is not None and str(args.mr) != str(run.get("mr")):
            conflicts.append(f"mr: run={run.get('mr')} vs arg={args.mr}")
        if conflicts:
            return emit(False, {"errors": [{"code": "param_conflict",
                        "detail": "; ".join(conflicts)}]}, 1)

    added, updated = [], []
    for nid, node in incoming.items():
        if nid in run["nodes"]:
            updated.append(nid)
        else:
            added.append(nid)
            # 进度只在首次录入时初始化,重录不回退已完成的节点
            run["progress"][nid] = {"status": "pending", "pr": None, "error": None}
        run["nodes"][nid] = node

    if run["root"] not in run["nodes"]:
        return emit(False, {"errors": [{"code": "unknown_root", "where": run["root"]}]}, 1)

    save_run(args.run, run)
    return emit(True, {"added": sorted(added), "updated": sorted(updated),
                       "undiscovered": undiscovered(run["nodes"])})


def cmd_status(args):
    run = load_run(args.run)
    if run is None:
        return emit(False, {"errors": [{"code": "no_run", "where": args.run}]}, 1)

    pending_discovery = undiscovered(run["nodes"])
    order, cycle_edges, unreachable = plan(run)
    counts = {s: 0 for s in STATUSES}
    for nid in run["nodes"]:
        counts[run["progress"][nid]["status"]] += 1

    out = {"root": run["root"], "role": run.get("role"), "mr": run.get("mr"),
           "counts": counts, "execution_order": order}
    if cycle_edges:
        out["cycle_edges"] = cycle_edges
    if unreachable:  # 从 root 到不了的节点,报出来不静默丢弃
        out["unreachable"] = unreachable
    if pending_discovery:
        out["undiscovered"] = pending_discovery

    if args.format == "table":
        print(render(run, out))
        return 0
    return emit(True, out)


def cmd_next(args):
    run = load_run(args.run)
    if run is None:
        return emit(False, {"errors": [{"code": "no_run", "where": args.run}]}, 1)

    missing = undiscovered(run["nodes"])
    if missing:  # 建树没完,现在发顺序会漏页
        return emit(False, {"errors": [dict(code="undiscovered_child", **m) for m in missing]}, 1)

    order, _, _ = plan(run)
    failed = [n for n in order if run["progress"][n]["status"] == "failed"]
    if failed:
        return emit(False, {"errors": [{"code": "blocked_by_failure", "where": n,
                                        "detail": run["progress"][n].get("error")}
                                       for n in failed]}, 1)

    target = None
    for nid in order:
        st = run["progress"][nid]["status"]
        if st == "doing":       # 上次中断在这里,续跑同一个
            target = nid
            break
        if st == "pending":
            target = nid
            break
    if target is None:
        return emit(True, {"done": True, "remaining": 0})

    run["progress"][target]["status"] = "doing"
    save_run(args.run, run)

    node = run["nodes"][target]
    deps = [{"node_id": k, "title": run["nodes"][k].get("title"),
             "route": run["nodes"][k].get("route"),
             "pr": run["progress"][k].get("pr")}
            for k in child_map(run["nodes"])[target]]
    remaining = sum(1 for n in order if run["progress"][n]["status"] != "done")
    return emit(True, {"node_id": target, "node": node, "depends_on": deps,
                       "remaining": remaining})


def cmd_mark(args):
    run = load_run(args.run)
    if run is None:
        return emit(False, {"errors": [{"code": "no_run", "where": args.run}]}, 1)
    if args.node not in run["nodes"]:
        return emit(False, {"errors": [{"code": "unknown_node", "where": args.node}]}, 1)
    if args.status == "failed" and not args.error:
        return emit(False, {"errors": [{"code": "missing_error",
                                        "detail": "标记 failed 必须给 --error"}]}, 1)

    cell = run["progress"][args.node]
    cell["status"] = args.status
    cell["error"] = args.error if args.status == "failed" else None
    if args.pr:
        cell["pr"] = args.pr
    save_run(args.run, run)

    order, _, _ = plan(run)
    return emit(True, {"node_id": args.node, "status": args.status,
                       "remaining": sum(1 for n in order
                                        if run["progress"][n]["status"] != "done")})


def render(run, out):
    nodes, progress = run["nodes"], run["progress"]
    kids = child_map(nodes)
    name = lambda i: nodes.get(i, {}).get("title", i)
    mark = {"pending": "·", "doing": "▶", "done": "✓", "failed": "✗"}
    lines = [f"root={name(run['root'])}  role={run.get('role')}  mr={run.get('mr')}  "
             + "  ".join(f"{k}={v}" for k, v in out["counts"].items()),
             "", "| # | 状态 | node | 标题 | 来源 | route | 依赖(先实现) | pr |",
             "|---|---|---|---|---|---|---|---|"]
    for i, nid in enumerate(out["execution_order"], 1):
        n, p = nodes[nid], progress[nid]
        deps = "、".join(name(k) for k in kids[nid]) or "—"
        lines.append(f"| {i} | {mark[p['status']]} | {nid} | {n.get('title','—')} | "
                     f"{n.get('source_skill','—')} | {n.get('route','—')} | {deps} | "
                     f"{p.get('pr') or '—'} |")
    for a, b in out.get("cycle_edges", []):
        lines.append(f"\n回边(按 route 绑定,不参与排序): {name(a)} → {name(b)}")
    if out.get("unreachable"):
        lines.append(f"\n从 root 不可达: {'、'.join(name(i) for i in out['unreachable'])}")
    for m in out.get("undiscovered", []):
        lines.append(f"\n未录入子节点: {name(m['where'])} → {m['detail']}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="iole.py")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("source", help="链接 → 存储适配 skill")
    s.add_argument("--link", required=True)
    s.set_defaults(fn=cmd_source)

    rec = sub.add_parser("record", help="把节点(含行数据)落盘")
    rec.add_argument("--nodes", required=True)
    rec.add_argument("--root")
    rec.add_argument("--link")
    rec.add_argument("--role")
    rec.add_argument("--mr", type=int, default=0, choices=(0, 1, 2))
    rec.set_defaults(fn=cmd_record)

    st = sub.add_parser("status", help="计划 + 进度")
    st.add_argument("--format", choices=("json", "table"), default="json")
    st.set_defaults(fn=cmd_status)

    nx = sub.add_parser("next", help="交出下一个待做节点并标记 doing")
    nx.set_defaults(fn=cmd_next)

    mk = sub.add_parser("mark", help="标记节点状态")
    mk.add_argument("--node", required=True)
    mk.add_argument("--status", required=True, choices=STATUSES)
    mk.add_argument("--pr")
    mk.add_argument("--error")
    mk.set_defaults(fn=cmd_mark)

    for p in (rec, st, nx, mk):
        p.add_argument("--run", required=True)

    args = ap.parse_args(argv)
    import io
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        code = args.fn(args)
    finally:
        sys.stdout = old_stdout
    output = buf.getvalue()
    if output:
        print(output, end="")
    args_dict = {k: v for k, v in vars(args).items() if k not in ("fn",)}
    parsed = None
    try:
        parsed = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        parsed = output.strip()
    _log(args.cmd, args_dict, parsed)
    return code


if __name__ == "__main__":
    sys.exit(main())
