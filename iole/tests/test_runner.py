"""Acceptance through the public CLI, real processes and real IOLE/ICPL commands.

Only Codex, the external model/process boundary, is substituted. Reports here are
fixture data for orchestration checks, not claims of real application acceptance.
"""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[1] / "scripts" / "runner.py"
BOUNDARY = Path(__file__).resolve().parent / "fixtures" / "codex_boundary.py"


class RunnerContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="iole-runner-test-")
        self.project = Path(self.temp.name)
        self.run = self.project / ".codex/iole/fixture/run.json"
        self.run.parent.mkdir(parents=True)
        self.instructions = self.project / "caller.txt"
        self.instructions.write_text("Only the isolated fixture; mr0, no remote writes; implementation then tests.")
        self.engine = self.project / "codex-fixture"
        self.engine.write_text(f"#!{sys.executable}\nexec(compile(open({str(BOUNDARY)!r}).read(), {str(BOUNDARY)!r}, 'exec'))\n")
        self.engine.chmod(0o700)
        self.make_tree()

    def tearDown(self):
        state = self.run.parent / "headless/state.json"
        if state.exists():
            self.cli("stop", expect=None)
        self.temp.cleanup()

    def make_tree(self, count=1):
        nodes, progress, rows = {}, {}, []
        for i in range(count):
            nid, title, row = f"n{i}", f"Page{i}", f"r{i + 1}"
            nodes[nid] = {"title": title, "source_skill": "icpl", "link": str(self.project / "source.json"),
                          "route": f"page-{i}", "row": {"row_id": row},
                          "children": [f"n{i - 1}"] if i else []}
            progress[nid] = {"status": "pending", "pr": None, "error": None}
            rows.append({"row_id": row, "title": title, "payload": {}, "roles": {"frontend": {
                "status": "ready", "lease_token": None, "lease_until": None, "pr": None, "last_error": None}}})
        self.run.write_text(json.dumps({"schema": "iole.run", "root": f"n{count - 1}", "mr": 0,
                                       "role": "frontend", "link": str(self.project / "source.json"),
                                       "nodes": nodes, "progress": progress}))
        (self.project / "source.json").write_text(json.dumps({"schema": "iole-item.sheet", "rows": rows}))

    def mode(self, **values):
        (self.project / "boundary-mode.json").write_text(json.dumps(values))

    def cli(self, verb, *args, expect=0):
        command = [sys.executable, str(RUNNER), verb, "--run", str(self.run)]
        if verb == "start":
            command += ["--project", str(self.project), "--instructions", str(self.instructions),
                        "--codex", str(self.engine), "--skip-git-repo-check"]
        proc = subprocess.run(command + list(args), capture_output=True, text=True, timeout=20)
        if expect is not None:
            self.assertEqual(proc.returncode, expect, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def calls(self):
        path = self.project / "boundary-calls.jsonl"
        return [json.loads(s) for s in path.read_text().splitlines()] if path.exists() else []

    def await_condition(self, predicate, description):
        limit = time.monotonic() + 15
        while time.monotonic() < limit:
            value = predicate()
            if value:
                return value
            time.sleep(0.02)
        self.fail(description + ": " + json.dumps(self.cli("status")))

    def finished(self):
        def done():
            result = self.cli("status")
            s = result["runner"]
            return result if s and s["status"] in {"complete", "failed", "blocked", "stopped"} and not s["child_alive"] else None
        return self.await_condition(done, "runner did not reach an observed terminal state")

    def held(self):
        path = self.project / "boundary-ready.json"
        return self.await_condition(lambda: json.loads(path.read_text()) if path.exists() and path.stat().st_size else None,
                                    "external boundary was not reached")

    def test_two_pages_run_in_order_with_fresh_contexts_and_confirmed_acceptance(self):
        self.make_tree(2)
        self.cli("start")
        result = self.finished()
        self.assertEqual(result["runner"]["status"], "complete", result)
        calls = self.calls()
        self.assertEqual([(x["node"], x["phase"]) for x in calls], [
            ("n0", "prepare"), ("n0", "implement"), ("n0", "review"),
            ("n1", "prepare"), ("n1", "implement"), ("n1", "review"), (None, "finalize")])
        self.assertEqual(calls[0]["session"], calls[2]["session"])
        self.assertTrue(calls[2]["resume"])
        self.assertEqual(len({calls[i]["session"] for i in (0, 1, 3, 4, 6)}), 5)
        self.assertEqual(result["ledger"]["counts"]["done"], 2)
        self.assertEqual(result["runner"]["usage"], {"input_tokens": 700, "cached_input_tokens": 560,
                                                    "output_tokens": 70, "reasoning_output_tokens": 28})
        for row in json.loads((self.project / "source.json").read_text())["rows"]:
            self.assertEqual(row["roles"]["frontend"]["status"], "review")

    def test_query_during_wait_does_not_launch_a_model_or_claim_success(self):
        self.mode(hold=True)
        self.cli("start")
        self.held()
        for _ in range(3):
            result = self.cli("status")
            self.assertEqual(result["runner"]["phase"], "implement")
            self.assertEqual(result["runner"]["title"], "Page0")
            self.assertTrue(result["runner"]["child_alive"])
            self.assertEqual(result["runner"]["model_jobs"], 2)
            self.assertEqual(result["ledger"]["counts"]["done"], 0)
            self.assertIn("controlled external boundary", result["runner"]["last_progress"])
        self.assertEqual(len(self.calls()), 2)
        (self.project / "boundary-release").touch()
        self.assertEqual(self.finished()["runner"]["status"], "complete")
        self.assertEqual(len(self.calls()), 4)

    def test_abandoned_job_directory_does_not_block_recovery_or_erase_evidence(self):
        stale = self.run.parent / "headless/job-0001-prepare"
        stale.mkdir(parents=True)
        evidence = stale / "events.jsonl"
        evidence.write_text("prior interrupted startup evidence\n")
        self.cli("start")
        self.assertEqual(self.finished()["runner"]["status"], "complete")
        self.assertEqual(evidence.read_text(), "prior interrupted startup evidence\n")

    def test_stop_and_resume_keep_worker_identity_and_do_not_reclaim(self):
        self.mode(hold=True)
        self.cli("start")
        held = self.held()
        before = self.cli("status")["runner"]
        self.cli("stop")
        self.assertFalse(self.cli("status")["runner"]["child_alive"])
        self.mode()
        self.cli("resume", "--message", "Retain valid work; apply the updated boundary requirement.")
        result = self.finished()
        self.assertEqual(result["runner"]["status"], "complete", result)
        calls = self.calls()
        workers = [x for x in calls if x["phase"] == "implement"]
        self.assertEqual(len(workers), 2)
        self.assertEqual(workers[0]["session"], workers[1]["session"])
        self.assertEqual(len([x for x in calls if x["phase"] == "prepare"]), 1)
        self.assertIn("recover", [x["phase"] for x in calls])
        self.assertIn("updated boundary requirement", workers[1]["prompt"])
        self.assertIn("updated boundary requirement", [c for c in calls if c["phase"] == "review"][-1]["prompt"])
        self.assertEqual(before["session_ids"]["worker"], workers[1]["session"])
        check = subprocess.run(["ps", "-p", str(held["grandchild"]), "-o", "stat="], capture_output=True, text=True)
        self.assertTrue(check.returncode or check.stdout.strip().startswith("Z"), check.stdout)

    def test_second_runner_is_rejected_without_overwriting_the_first(self):
        self.mode(hold=True)
        self.cli("start")
        self.held()
        before = self.cli("status")["runner"]["session_ids"]
        error = self.cli("start", expect=1)
        self.assertIn("owns this workspace", error["error"])
        self.assertEqual(self.cli("status")["runner"]["session_ids"], before)
        self.assertEqual(len(self.calls()), 2)
        second = self.run.parent.parent / "second/run.json"
        second.parent.mkdir()
        second.write_bytes(self.run.read_bytes())
        result = self.cli("start", "--run", str(second), expect=1)
        self.assertIn("owns this workspace", result["error"])

    def test_independent_workspaces_can_run_concurrently(self):
        peer = RunnerContract()
        peer.setUp()
        try:
            self.mode(hold=True)
            peer.mode(hold=True)
            self.cli("start")
            peer.cli("start")
            self.held()
            peer.held()
            self.assertTrue(self.cli("status")["runner"]["child_alive"])
            self.assertTrue(peer.cli("status")["runner"]["child_alive"])
            (self.project / "boundary-release").touch()
            (peer.project / "boundary-release").touch()
            self.assertEqual(self.finished()["runner"]["status"], "complete")
            self.assertEqual(peer.finished()["runner"]["status"], "complete")
        finally:
            peer.tearDown()

    def test_stop_waits_for_a_descendant_that_ignores_graceful_termination(self):
        self.mode(hold=True, ignore_term=True)
        self.cli("start")
        held = self.held()
        try:
            self.cli("stop")
            check = subprocess.run(["ps", "-p", str(held["grandchild"]), "-o", "stat="], capture_output=True, text=True)
            self.assertTrue(check.returncode or check.stdout.strip().startswith("Z"),
                            "stop reported success while the owned process group still had a live child")
        finally:
            try:
                os.kill(held["grandchild"], signal.SIGKILL)
            except ProcessLookupError:
                pass

    def test_disappeared_leader_does_not_hide_a_live_process_group(self):
        self.mode(hold=True)
        self.cli("start")
        held = self.held()
        try:
            os.kill(held["pid"], signal.SIGKILL)
            stopped = self.cli("stop", expect=None)
            result = self.cli("status")["runner"]
            if stopped["ok"]:
                check = subprocess.run(["ps", "-p", str(held["grandchild"]), "-o", "stat="], capture_output=True, text=True)
                self.assertTrue(check.returncode or check.stdout.strip().startswith("Z"))
            else:
                self.assertIn("not yet confirmed", stopped["error"])
                self.assertTrue(result["child_alive"])
                self.assertEqual(result["status"], "failed")
                self.cli("resume", expect=1)
        finally:
            try:
                os.kill(held["grandchild"], signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.cli("stop")
        self.mode()
        self.cli("resume")
        self.assertEqual(self.finished()["runner"]["status"], "complete")

    def test_stop_cleans_descendants_in_independent_process_groups(self):
        for ignores_signal in (False, True):
            with self.subTest(ignores_signal=ignores_signal):
                self.mode(hold=True, detached=True, ignore_term=ignores_signal)
                self.cli("start")
                held = self.held()
                try:
                    self.cli("stop")
                    check = subprocess.run(["ps", "-p", str(held["grandchild"]), "-o", "stat="], capture_output=True, text=True)
                    self.assertTrue(check.returncode or check.stdout.strip().startswith("Z"),
                                    "detached owned command survived stop")
                finally:
                    try:
                        os.kill(held["grandchild"], signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            self.tearDown()
            self.setUp()

    def test_preexisting_owner_is_not_adopted_or_reset(self):
        data = json.loads(self.run.read_text())
        data["progress"]["n0"]["status"] = "doing"
        self.run.write_text(json.dumps(data))
        before = self.run.read_bytes()
        result = self.cli("start", expect=1)
        self.assertIn("Existing implementation owner", result["error"])
        self.assertEqual(self.run.read_bytes(), before)
        self.assertEqual(self.calls(), [])

    def test_bad_or_incomplete_child_results_never_advance(self):
        cases = [{"bad_result": x} for x in ("wrong_node", "wrong_type", "missing_field", "malformed")]
        cases += [{"nonzero_exit": True}, {"no_completion": True}]
        for mode in cases:
            with self.subTest(mode=mode):
                self.mode(**mode)
                self.cli("start")
                result = self.finished()
                self.assertEqual(result["runner"]["status"], "failed", result)
                self.assertEqual(result["ledger"]["counts"]["doing"], 1)
                self.assertEqual([c["phase"] for c in self.calls()], ["prepare", "implement"])
            self.tearDown()
            self.setUp()

    def test_missing_evidence_or_unconfirmed_writeback_cannot_complete(self):
        for mode in ({"missing_evidence": True}, {"unconfirmed_sync": True}):
            with self.subTest(mode=mode):
                self.mode(**mode)
                self.cli("start")
                result = self.finished()
                self.assertEqual(result["runner"]["status"], "failed", result)
                self.assertNotIn("finalize", [c["phase"] for c in self.calls()])
            self.tearDown()
            self.setUp()

    def test_source_sync_recovery_does_not_reimplement_the_page(self):
        self.mode(writeback_interrupted=True)
        self.cli("start")
        self.assertEqual(self.finished()["runner"]["status"], "failed")
        self.assertEqual(json.loads((self.project / "source.json").read_text())["rows"][0]["roles"]["frontend"]["status"], "review")
        self.mode()
        self.cli("resume")
        result = self.finished()
        self.assertEqual(result["runner"]["status"], "complete", result)
        self.assertEqual(len([x for x in self.calls() if x["phase"] == "implement"]), 1)
        reviews = [x for x in self.calls() if x["phase"] == "review"]
        self.assertEqual(reviews[0]["job"]["worker_result"], reviews[1]["job"]["worker_result"])
        self.assertEqual(json.loads(Path(reviews[1]["job"]["worker_result"]).read_text())["outcome"], "done")

    def test_rejected_review_can_reconcile_without_replaying_implementation(self):
        self.mode(unconfirmed_sync=True)
        self.cli("start")
        self.assertEqual(self.finished()["runner"]["status"], "failed")
        self.mode()
        self.cli("resume")
        result = self.finished()
        self.assertEqual(result["runner"]["status"], "complete", result)
        self.assertEqual(len([c for c in self.calls() if c["phase"] == "implement"]), 1)

    def test_reviewer_repairs_resume_the_same_worker(self):
        self.mode(revision=True)
        self.cli("start")
        result = self.finished()
        self.assertEqual(result["runner"]["status"], "complete", result)
        workers = [x for x in self.calls() if x["phase"] == "implement"]
        self.assertEqual(len(workers), 2)
        self.assertEqual(workers[0]["session"], workers[1]["session"])
        self.assertIsNotNone(workers[1]["job"]["feedback"])

    def test_completed_worker_checkpoint_is_reused_after_crash_recovery(self):
        self.mode(hold_phase="review")
        self.cli("start")
        self.held()
        self.cli("stop")
        path = self.run.parent / "headless/state.json"
        state = json.loads(path.read_text())
        # Replay the durable checkpoint immediately after a real worker result
        # was accepted, before the supervisor advanced to review.
        worker_result = state["worker_result"]
        state.update(phase="implement", job={"phase": "implement", "result": worker_result, "complete": True})
        path.write_text(json.dumps(state))
        before = len([c for c in self.calls() if c["phase"] == "implement"])
        self.mode()
        self.cli("resume")
        result = self.finished()
        self.assertEqual(result["runner"]["status"], "complete", result)
        self.assertEqual(len([c for c in self.calls() if c["phase"] == "implement"]), before)
        self.assertEqual([c for c in self.calls() if c["phase"] == "review"][-1]["job"]["worker_result"], worker_result)

    def test_durable_selection_resumes_before_or_after_ledger_mark(self):
        for ledger_status in ("pending", "doing"):
            with self.subTest(ledger_status=ledger_status):
                self.mode(hold_phase="prepare")
                self.cli("start")
                self.held()
                self.cli("stop")
                tree = json.loads(self.run.read_text())
                tree["progress"]["n0"]["status"] = ledger_status
                self.run.write_text(json.dumps(tree))
                # Both sides of the selection write retain the observed owner.
                self.mode()
                self.cli("resume")
                self.assertEqual(self.finished()["runner"]["status"], "complete")
            self.tearDown()
            self.setUp()

    def test_lease_risk_stops_before_another_implementation_call(self):
        self.mode(lease_soon=True)
        self.cli("start")
        result = self.finished()
        self.assertEqual(result["runner"]["status"], "blocked", result)
        self.assertIn("Lease", result["runner"]["error"])
        self.assertEqual([c["phase"] for c in self.calls()], ["prepare"])

    def test_missing_lease_does_not_bypass_ownership_protection(self):
        self.mode(missing_lease=True)
        self.cli("start")
        result = self.finished()
        self.assertEqual(result["runner"]["status"], "failed", result)
        self.assertEqual([c["phase"] for c in self.calls()], ["prepare"])

    def test_lease_deadline_interrupts_an_active_worker(self):
        self.mode(hold=True, lease_seconds=62)
        self.cli("start")
        self.held()
        result = self.finished()
        self.assertEqual(result["runner"]["status"], "blocked", result)
        self.assertFalse(result["runner"]["child_alive"])
        self.assertNotIn("review", [c["phase"] for c in self.calls()])

    def test_resume_refuses_a_foreign_source_owner(self):
        self.mode(hold=True)
        self.cli("start")
        self.held()
        self.cli("stop")
        path = self.project / "source.json"
        source = json.loads(path.read_text())
        source["rows"][0]["roles"]["frontend"]["lease_token"] = "another-owner"
        path.write_text(json.dumps(source))
        before = path.read_bytes()
        self.mode()
        self.cli("resume")
        self.assertEqual(self.finished()["runner"]["status"], "blocked")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len([c for c in self.calls() if c["phase"] == "implement"]), 1)

    def test_exhausted_schedule_does_not_bypass_tree_acceptance(self):
        self.mode(tree_blocked=True)
        self.cli("start")
        result = self.finished()
        self.assertEqual(result["ledger"]["counts"]["done"], 1)
        self.assertEqual(result["runner"]["status"], "blocked")
        self.assertIn("Cross-page", result["runner"]["error"])
        self.mode()
        self.cli("resume")
        self.assertEqual(self.finished()["runner"]["status"], "complete")
        self.assertEqual(len([c for c in self.calls() if c["phase"] == "implement"]), 1)

    def test_tree_repair_keeps_audit_feedback_and_targets_only_the_defective_page(self):
        self.make_tree(2)
        self.mode(tree_revision=True)
        self.cli("start")
        result = self.finished()
        self.assertEqual(result["runner"]["status"], "complete", result)
        workers = [c for c in self.calls() if c["phase"] == "implement"]
        self.assertEqual([c["node"] for c in workers], ["n0", "n1", "n0"])
        feedback = json.loads(Path(workers[-1]["job"]["feedback"]).read_text())
        self.assertIn("cross-page defect", feedback["summary"])

    def test_final_audit_cannot_dispatch_an_unreachable_page(self):
        tree = json.loads(self.run.read_text())
        tree["nodes"]["outside"] = {**tree["nodes"]["n0"], "title": "OutsideScope"}
        tree["progress"]["outside"] = {"status": "pending", "pr": None, "error": None}
        self.run.write_text(json.dumps(tree))
        self.mode(tree_revision=True, repair_node="outside")
        self.cli("start")
        result = self.finished()
        self.assertEqual(result["runner"]["status"], "failed", result)
        self.assertEqual(json.loads(self.run.read_text())["progress"]["outside"]["status"], "pending")
        self.assertNotIn("outside", [c["node"] for c in self.calls()])

    def test_preparation_can_resume_after_a_reported_blocker(self):
        self.mode(prepare_blocked=True)
        self.cli("start")
        self.assertEqual(self.finished()["runner"]["status"], "blocked")
        claim = (self.project / "boundary-claims.json").read_bytes()
        # A prepared claim is an external effect that remains after a blocker.
        # Use the recovery path, never claim it a second time.
        self.mode()
        self.cli("resume")
        self.assertEqual(self.finished()["runner"]["status"], "complete")
        self.assertEqual((self.project / "boundary-claims.json").read_bytes(), claim)

    def test_blocked_phase_can_be_retried_after_prerequisite_is_restored(self):
        self.mode(blocked=True)
        self.cli("start")
        self.assertEqual(self.finished()["runner"]["status"], "blocked")
        self.mode()
        self.cli("resume")
        result = self.finished()
        self.assertEqual(result["runner"]["status"], "complete", result)

    def test_supervisor_crash_preserves_child_lock_until_explicit_stop(self):
        self.mode(hold=True)
        self.cli("start")
        self.held()
        state = json.loads((self.run.parent / "headless/state.json").read_text())
        os.kill(state["daemon"]["pid"], signal.SIGKILL)
        self.await_condition(lambda: not self.cli("status")["runner"]["supervisor_alive"], "supervisor did not exit")
        result = self.cli("status")["runner"]
        self.assertTrue(result["child_alive"])
        self.assertEqual(result["status"], "interrupted")
        self.cli("resume", expect=1)
        self.cli("stop")
        self.mode()
        self.cli("resume")
        self.assertEqual(self.finished()["runner"]["status"], "complete")


if __name__ == "__main__":
    unittest.main()
