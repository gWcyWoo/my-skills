import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "iole.py"
SHEET = ("https://docs.google.com/spreadsheets/d/"
         "1KOL3kdlHKWc-eUSD89ebZGBYeH6eudchYsggcFnVkHQ/edit?gid=0#gid=0")


def run(*argv, expect=0):
    p = subprocess.run([sys.executable, str(SCRIPT), *argv], capture_output=True, text=True)
    assert p.returncode == expect, f"{argv}\nrc={p.returncode}\n{p.stdout}\n{p.stderr}"
    return json.loads(p.stdout) if p.stdout.lstrip().startswith("{") else p.stdout


def node(title, children=(), **kw):
    base = {"title": title, "source_skill": "icps", "route": title.lower(),
            "row": {"design_urls": [], "ui_description": ""},
            "children": list(children)}
    base.update(kw)   # kw 覆盖默认值
    return base


class TestSourceFactory(unittest.TestCase):

    def test_google_sheet_routes_to_icps(self):
        src = run("source", "--link", SHEET)["source"]
        self.assertEqual((src["skill"], src["kind"], src["gid"]), ("icps", "google-sheet", "0"))
        self.assertEqual(src["doc_id"], "1KOL3kdlHKWc-eUSD89ebZGBYeH6eudchYsggcFnVkHQ")

    def test_dingtalk_and_feishu_route_to_their_skills(self):
        self.assertEqual(run("source", "--link",
                             "https://alidocs.dingtalk.com/i/nodes/abcd1234")["source"]["skill"],
                         "icpd")
        self.assertEqual(run("source", "--link",
                             "https://x.feishu.cn/sheets/Ab3Kd9")["source"]["skill"], "icpf")

    def test_local_file_routes_to_icpl(self):
        src = run("source", "--link", "/tmp/sheet.json")["source"]
        self.assertEqual((src["skill"], src["kind"]), ("icpl", "local-file"))
        src2 = run("source", "--link", "./data/test.json")["source"]
        self.assertEqual(src2["skill"], "icpl")

    def test_unregistered_source_halts(self):
        out = run("source", "--link", "https://example.com/x", expect=1)
        self.assertEqual(out["errors"][0]["code"], "unknown_source")


class Ledger(unittest.TestCase):

    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        doc_dir = self.base / "iole" / "testdoc"
        doc_dir.mkdir(parents=True)
        self.run_f = doc_dir / "run.json"
        self.seq = 0

    def record(self, nodes, root=None, expect=0, **kw):
        self.seq += 1
        f = self.base / f"n{self.seq}.json"
        f.write_text(json.dumps({"nodes": nodes}, ensure_ascii=False), encoding="utf-8")
        argv = ["record", "--run", str(self.run_f), "--nodes", str(f)]
        if root:
            argv += ["--root", root, "--link", SHEET, "--role", "frontend",
                     "--mr", str(kw.get("mr", 0))]
        return run(*argv, expect=expect)

    def next(self, expect=0):
        return run("next", "--run", str(self.run_f), expect=expect)

    def mark(self, nid, status, expect=0, **kw):
        argv = ["mark", "--run", str(self.run_f), "--node", nid, "--status", status]
        for k in ("pr", "error"):
            if kw.get(k):
                argv += [f"--{k}", kw[k]]
        if status in ("done", "partial") and not kw.get("skip_evidence"):
            run_data = json.loads(self.run_f.read_text())
            if nid not in run_data["nodes"]:
                return run(*argv, expect=expect)
            title = run_data["nodes"][nid].get("title", nid)
            icp_dir = self.base / "icp" / title
            icp_dir.mkdir(parents=True, exist_ok=True)
            for f in ("layout-blueprint.json", "api-contract.json"):
                (icp_dir / f).write_text(json.dumps({"components": [{"name": title}]}))
            if status == "done":
                (icp_dir / "behavior-result.json").write_text(json.dumps({
                    "behavior_total": 1, "behavior_passed": 1,
                    "positive": {"total": 1, "passed": 1, "failed": []},
                    "negative": {"total": 0, "passed": 0, "failed": []},
                    "mock_violations": []}))
        return run(*argv, expect=expect)

    def status(self, fmt="json", expect=0):
        return run("status", "--run", str(self.run_f), "--format", fmt, expect=expect)

    def chain(self):
        """A → B → C,一次录全。"""
        self.record({"a": node("A", ["b"]), "b": node("B", ["c"]), "c": node("C")}, root="a")


class TestRecord(Ledger):

    def test_first_record_creates_run_with_all_pending(self):
        out = self.record({"a": node("A")}, root="a")
        self.assertEqual(out["added"], ["a"])
        self.assertEqual(self.status()["counts"], {"pending": 1, "doing": 0,
                                                   "done": 0, "partial": 0,
                                                   "failed": 0})

    def test_row_data_from_icpx_is_persisted(self):
        self.record({"a": node("A", row={"route": "signin", "ui_description": "结构分为4部份"})},
                    root="a")
        saved = json.loads(self.run_f.read_text())["nodes"]["a"]["row"]
        self.assertEqual(saved["ui_description"], "结构分为4部份")

    def test_undiscovered_children_are_reported(self):
        out = self.record({"a": node("A", ["b"])}, root="a")
        self.assertEqual(out["undiscovered"], [{"where": "a", "detail": "b"}])
        out = self.record({"b": node("B")})
        self.assertEqual(out["undiscovered"], [])

    def test_re_record_updates_data_but_never_rolls_back_progress(self):
        self.chain()
        self.next()
        self.mark("c", "done", pr="mr/1")
        out = self.record({"c": node("C", route="new-route")})
        self.assertEqual(out["updated"], ["c"])
        prog = json.loads(self.run_f.read_text())["progress"]["c"]
        self.assertEqual((prog["status"], prog["pr"]), ("done", "mr/1"))
        self.assertEqual(json.loads(self.run_f.read_text())["nodes"]["c"]["route"], "new-route")

    def test_first_record_without_root_halts(self):
        out = self.record({"a": node("A")}, expect=1)
        self.assertEqual(out["errors"][0]["code"], "missing_root")


class TestOneAtATime(Ledger):

    def test_next_check_selects_without_changing_ownership(self):
        self.chain()
        before = self.run_f.read_bytes()
        selected = run("next", "--run", str(self.run_f), "--check")
        self.assertEqual(selected["node_id"], "c")
        self.assertEqual(self.run_f.read_bytes(), before)
        self.assertEqual(self.next()["node_id"], selected["node_id"])

    def test_hands_out_leaves_first_one_at_a_time(self):
        self.chain()
        self.assertEqual(self.next()["node_id"], "c")
        self.mark("c", "done")
        self.assertEqual(self.next()["node_id"], "b")
        self.mark("b", "done")
        self.assertEqual(self.next()["node_id"], "a")
        self.mark("a", "done")
        self.assertTrue(self.next()["done"])

    def test_next_skips_doing_and_returns_waiting(self):
        """doing 节点由对应 agent 负责,next 不重复派发;无可派发节点时返回 waiting。"""
        self.chain()
        self.assertEqual(self.next()["node_id"], "c")
        self.assertEqual(self.status()["counts"]["doing"], 1)
        out = self.next()
        self.assertFalse(out["done"])
        self.assertIn("c", out["waiting"])

    def test_next_carries_row_data_and_implemented_dependencies(self):
        self.chain()
        self.mark("c", "done", pr="mr/9")
        out = self.next()
        self.assertEqual(out["node_id"], "b")
        self.assertEqual(out["node"]["row"], {"design_urls": [], "ui_description": ""})
        self.assertEqual(out["depends_on"],
                         [{"node_id": "c", "title": "C", "route": "c", "pr": "mr/9"}])

    def test_remaining_counts_down(self):
        self.chain()
        self.assertEqual(self.next()["remaining"], 3)
        self.assertEqual(self.mark("c", "done")["remaining"], 2)

    def test_next_refuses_while_the_tree_is_incomplete(self):
        """建树没完就发顺序会漏页。"""
        self.record({"a": node("A", ["b"])}, root="a")
        out = self.next(expect=1)
        self.assertEqual(out["errors"][0]["code"], "undiscovered_child")

    def test_failure_does_not_block_parent(self):
        """failed 节点不阻塞祖先——兄弟 done 后父节点可派发。"""
        self.record({"a": node("A", ["b", "c"]),
                      "b": node("B"), "c": node("C")}, root="a")
        first = self.next()["node_id"]
        self.mark(first, "failed", error="设计稿解析失败")
        sibling = "c" if first == "b" else "b"
        self.assertEqual(self.next()["node_id"], sibling)
        self.mark(sibling, "done")
        self.assertEqual(self.next()["node_id"], "a")
        self.mark("a", "done")
        out = self.next()
        self.assertTrue(out["done"])
        self.assertEqual(out["skipped"], [first])

    def test_mark_failed_requires_a_reason(self):
        self.chain()
        self.assertEqual(self.mark("c", "failed", expect=1)["errors"][0]["code"],
                         "missing_error")

    def test_exhausted_schedule_reports_partial_without_changing_progress(self):
        self.record({"a": node("A", ["b", "c"]),
                     "b": node("B"), "c": node("C")}, root="a")
        self.mark("b", "partial", error="页面接线缺证据")
        self.mark("c", "failed", error="合同不可用")
        self.mark("a", "done")
        before = self.run_f.read_bytes()
        out = self.next()
        self.assertTrue(out["done"])  # 调度耗尽，不能据此认定验收通过。
        self.assertEqual(out["remaining"], 0)
        self.assertEqual(out["skipped"], ["b", "c"])
        self.assertEqual(self.run_f.read_bytes(), before)

    def test_mark_unknown_node_halts(self):
        self.chain()
        self.assertEqual(self.mark("ghost", "done", expect=1)["errors"][0]["code"],
                         "unknown_node")

    def test_mark_done_missing_evidence_rejected(self):
        self.chain()
        out = self.mark("c", "done", expect=1, skip_evidence=True)
        self.assertEqual(out["errors"][0]["code"], "missing_evidence")

    def test_done_requires_behavior_result_without_changing_ledger(self):
        self.record({"a": node("A")}, root="a")
        self.mark("a", "partial", error="尚未验证")
        before = self.run_f.read_bytes()
        out = self.mark("a", "done", expect=1, skip_evidence=True)
        self.assertEqual(out["errors"][0]["code"], "missing_evidence")
        self.assertIn("behavior-result.json", out["errors"][0]["detail"])
        self.assertEqual(self.run_f.read_bytes(), before)

    def test_mark_done_with_valid_evidence_accepted(self):
        self.chain()
        out = self.mark("c", "done")
        self.assertEqual(out["status"], "done")

    def test_done_rejects_invalid_or_unsuccessful_behavior_results(self):
        self.record({"a": node("A")}, root="a")
        self.mark("a", "done")
        report = self.base / "icp" / "A" / "behavior-result.json"
        valid = json.loads(report.read_text())
        self.mark("a", "pending")
        before = self.run_f.read_bytes()
        invalid = ["not json", "[]", "{}"]
        for changes in (
            {"behavior_total": 0, "behavior_passed": 0},
            {"behavior_passed": 0}, {"behavior_total": True},
            {"positive": {"total": 1, "passed": 1, "failed": ["failure"]}},
            {"negative": {"total": 1, "passed": 1, "failed": []}},
            {"negative": {"total": -1, "passed": -1, "failed": []}},
            {"negative": None}, {"mock_violations": ["chain mock"]},
        ):
            invalid.append(json.dumps({**valid, **changes}))
        for payload in invalid:
            with self.subTest(payload=payload):
                self.mark("a", "pending")
                report.write_text(payload)
                out = self.mark("a", "done", expect=1, skip_evidence=True)
                self.assertEqual(out["errors"][0]["code"], "invalid_behavior_result")
                self.assertEqual(self.run_f.read_bytes(), before)
        report.write_text(json.dumps(valid))
        self.assertEqual(self.mark("a", "done", skip_evidence=True)["status"], "done")

    def test_done_rejects_unreadable_or_empty_artifacts(self):
        self.record({"a": node("A")}, root="a")
        self.mark("a", "done")
        for filename in ("layout-blueprint.json", "api-contract.json"):
            artifact = self.base / "icp" / "A" / filename
            valid = artifact.read_bytes()
            for payload in (b"not json", b"{}", b"[]", b"\xff"):
                with self.subTest(filename=filename, payload=payload):
                    self.mark("a", "pending")
                    before = self.run_f.read_bytes()
                    artifact.write_bytes(payload)
                    out = self.mark("a", "done", expect=1, skip_evidence=True)
                    self.assertEqual(out["errors"][0]["code"], "invalid_evidence")
                    self.assertEqual(self.run_f.read_bytes(), before)
            artifact.write_bytes(valid)

    def test_completion_preflight_validates_without_writing(self):
        self.record({"a": node("A")}, root="a")
        self.mark("a", "done")
        self.mark("a", "pending")
        before = self.run_f.read_bytes()
        args = ["mark", "--run", str(self.run_f), "--node", "a", "--check"]
        run(*args, "--status", "done")
        self.assertEqual(self.run_f.read_bytes(), before)
        out = run(*args, "--status", "pending", expect=1)
        self.assertEqual(out["errors"][0]["code"], "check_requires_done")
        self.assertEqual(self.run_f.read_bytes(), before)
        (self.base / "icp" / "A" / "behavior-result.json").write_text("{}")
        out = run(*args, "--status", "done", expect=1)
        self.assertEqual(out["errors"][0]["code"], "invalid_behavior_result")
        self.assertEqual(self.run_f.read_bytes(), before)
        self.assertEqual(self.mark("a", "partial", error="待验证", skip_evidence=True)["status"], "partial")

    def test_mark_done_missing_title_rejected(self):
        self.record({"x": {"source_skill": "icps", "route": "x",
                           "row": {}, "children": []}}, root="x")
        out = self.mark("x", "done", expect=1, skip_evidence=True)
        self.assertEqual(out["errors"][0]["code"], "missing_title")


class TestTreeShape(Ledger):

    def test_heterogeneous_nodes_order_the_same(self):
        """树里混不同来源的节点——排序只看 children,与节点类型无关。"""
        self.record({"s:登录": dict(node("登录", ["d:客服"]), source_skill="icps"),
                     "d:客服": dict(node("客服", ["f:协议"]), source_skill="icpd"),
                     "f:协议": dict(node("协议"), source_skill="icpf")}, root="s:登录")
        self.assertEqual(self.status()["execution_order"], ["f:协议", "d:客服", "s:登录"])

    def test_shared_dependency_built_once(self):
        self.record({"a": node("A", ["b", "c"]), "b": node("B", ["d"]),
                     "c": node("C", ["d"]), "d": node("D")}, root="a")
        order = self.status()["execution_order"]
        self.assertEqual((order[0], order[-1], len(order)), ("d", "a", 4))

    def test_navigation_cycle_reported_not_fatal(self):
        """登录 → 验证码 → 首页 → 登录 是正常导航,不是错误。"""
        self.record({"登录": node("登录", ["验证码"]), "验证码": node("验证码", ["首页"]),
                     "首页": node("首页", ["登录"])}, root="登录")
        out = self.status()
        self.assertEqual(out["cycle_edges"], [["首页", "登录"]])
        self.assertEqual(out["execution_order"], ["首页", "验证码", "登录"])

    def test_self_reference_does_not_deadlock(self):
        self.record({"a": node("A", ["a"])}, root="a")
        self.assertEqual(self.status()["execution_order"], ["a"])

    def test_unreachable_reported_not_dropped(self):
        self.record({"a": node("A"), "orphan": node("Orphan")}, root="a")
        before = self.run_f.read_bytes()
        out = self.status()
        self.assertEqual(out["unreachable"], ["orphan"])
        self.assertEqual(out["execution_order"], ["a"])
        self.assertEqual(out["counts"], {"pending": 1, "doing": 0, "done": 0,
                                         "partial": 0, "failed": 0})
        self.assertIn("pending=1", self.status(fmt="table"))
        self.assertEqual(self.run_f.read_bytes(), before)

    def test_status_table(self):
        self.chain()
        self.mark("c", "done", pr="mr/3")
        out = self.status(fmt="table")
        self.assertIn("| 1 | ✓ | c | C | icps | c | — | mr/3 |", out)
        self.assertIn("pending=2", out)

    def test_status_without_a_run_halts(self):
        self.assertEqual(self.status(expect=1)["errors"][0]["code"], "no_run")


class TestPick(Ledger):

    def pick(self, title, expect=0):
        return run("pick", "--run", str(self.run_f), "--title", title, expect=expect)

    def test_pick_finds_node_by_title(self):
        self.chain()
        self.mark("c", "done", pr="mr/1")
        out = self.pick("B")
        self.assertEqual(out["node_id"], "b")
        self.assertEqual(out["node"]["title"], "B")
        self.assertEqual(out["node"]["row"], {"design_urls": [], "ui_description": ""})
        self.assertEqual(out["depends_on"],
                         [{"node_id": "c", "title": "C", "route": "c", "pr": "mr/1"}])
        self.assertEqual(out["remaining"], 2)
        prog = json.loads(self.run_f.read_text())["progress"]["b"]
        self.assertEqual(prog["status"], "doing")

    def test_pick_unknown_title_halts(self):
        self.chain()
        out = self.pick("不存在", expect=1)
        self.assertEqual(out["errors"][0]["code"], "unknown_title")

    def test_pick_duplicate_title_halts(self):
        self.record({"a": node("A", ["b", "c"]),
                      "b": node("X"), "c": node("X")}, root="a")
        out = self.pick("X", expect=1)
        self.assertEqual(out["errors"][0]["code"], "duplicate_title")

    def test_pick_resets_done_node_to_doing(self):
        """fix 场景:已 done 的节点可被 pick 重新标为 doing。"""
        self.chain()
        self.next()
        self.mark("c", "done")
        out = self.pick("C")
        self.assertEqual(out["node_id"], "c")
        prog = json.loads(self.run_f.read_text())["progress"]["c"]
        self.assertEqual(prog["status"], "doing")

    def test_pick_clears_stale_error(self):
        """pick failed 节点时清除旧 error。"""
        self.chain()
        self.next()
        self.mark("c", "failed", error="设计稿解析失败")
        self.pick("C")
        prog = json.loads(self.run_f.read_text())["progress"]["c"]
        self.assertEqual(prog["status"], "doing")
        self.assertIsNone(prog["error"])

    def test_pick_does_not_affect_next(self):
        """pick 标 doing 的节点,next 跳过它,不重复派发。"""
        self.chain()
        self.pick("B")
        self.assertEqual(self.next()["node_id"], "c")
        self.mark("c", "done")
        out = self.next()
        self.assertFalse(out["done"])
        self.assertIn("b", out["waiting"])


if __name__ == "__main__":
    unittest.main()
