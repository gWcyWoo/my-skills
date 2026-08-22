import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "icpl.py"


def run(*argv, expect=0):
    p = subprocess.run([sys.executable, str(SCRIPT), *argv], capture_output=True, text=True)
    out = json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else {}
    if expect is not None:
        assert p.returncode == expect, f"{argv}\nrc={p.returncode}\n{p.stdout}\n{p.stderr}"
    return p.returncode, out


def make_backend(tmp: Path):
    backend = tmp / "sheet.json"
    rows = []
    for i in (1, 2, 3):
        rows.append({"row_id": f"r{i}", "title": f"页面{i}", "payload": {"design": f"d{i}"},
                     "roles": {"frontend": {"status": "ready", "lease_token": None,
                                            "lease_until": None, "pr": None, "last_error": None}}})
    backend.write_text(json.dumps({"schema": "iole-item.sheet", "rows": rows},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
    return backend


class TestIcpl(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.backend = make_backend(self.tmp)

    def _snapshot(self):
        return json.loads(self.backend.read_text())

    def test_inspect_by_status(self):
        rc, out = run("inspect", "--link", str(self.backend), "--role", "frontend",
                      "--status", "ready")
        self.assertEqual(out["row"]["row_id"], "r1")

    def test_inspect_by_title(self):
        rc, out = run("inspect", "--link", str(self.backend), "--role", "frontend",
                      "--title", "页面2")
        self.assertEqual(out["row"]["row_id"], "r2")

    def test_inspect_by_title_not_found(self):
        rc, out = run("inspect", "--link", str(self.backend), "--role", "frontend",
                      "--title", "不存在")
        self.assertIsNone(out["row"])

    def test_inspect_claim_atomic_read_and_lock(self):
        rc, out = run("inspect", "--link", str(self.backend), "--role", "frontend",
                      "--status", "ready", "--claim", "doing")
        self.assertEqual(out["row"]["row_id"], "r1")
        self.assertIn("lease_token", out)
        snap = self._snapshot()
        cell = next(r for r in snap["rows"] if r["row_id"] == "r1")["roles"]["frontend"]
        self.assertEqual(cell["status"], "doing")
        self.assertEqual(cell["lease_token"], out["lease_token"])

    def test_inspect_claim_skips_already_claimed(self):
        run("inspect", "--link", str(self.backend), "--role", "frontend",
            "--status", "ready", "--claim", "doing")
        rc, out = run("inspect", "--link", str(self.backend), "--role", "frontend",
                      "--status", "ready", "--claim", "doing")
        self.assertEqual(out["row"]["row_id"], "r2")

    def test_claim_to_review_with_lease_token(self):
        _, ins = run("inspect", "--link", str(self.backend), "--role", "frontend",
                     "--status", "ready", "--claim", "doing")
        token = ins["lease_token"]
        rc, out = run("claim", "--link", str(self.backend), "--role", "frontend",
                      "--row-ids", "r1", "--status", "review", "--lease-token", token,
                      "--pr", "MR-1")
        self.assertEqual(out["status"], "review")
        snap = self._snapshot()
        cell = next(r for r in snap["rows"] if r["row_id"] == "r1")["roles"]["frontend"]
        self.assertEqual(cell["status"], "review")
        self.assertEqual(cell["pr"], "MR-1")
        self.assertIsNone(cell["lease_token"])

    def test_claim_stale_lease_rejected(self):
        run("inspect", "--link", str(self.backend), "--role", "frontend",
            "--status", "ready", "--claim", "doing")
        rc, out = run("claim", "--link", str(self.backend), "--role", "frontend",
                      "--row-ids", "r1", "--status", "review", "--lease-token", "wrong",
                      expect=1)
        self.assertEqual(out["errors"][0]["code"], "stale_lease")

    def test_claim_to_ready_with_error_releases_lease(self):
        _, ins = run("inspect", "--link", str(self.backend), "--role", "frontend",
                     "--status", "ready", "--claim", "doing")
        rc, out = run("claim", "--link", str(self.backend), "--role", "frontend",
                      "--row-ids", ins["row"]["row_id"], "--status", "ready",
                      "--error", "analyze failed")
        snap = self._snapshot()
        cell = next(r for r in snap["rows"] if r["row_id"] == "r1")["roles"]["frontend"]
        self.assertEqual(cell["status"], "ready")
        self.assertIsNone(cell["lease_token"])
        self.assertEqual(cell["last_error"], "analyze failed")

    def test_claim_unknown_row_rejected(self):
        rc, out = run("claim", "--link", str(self.backend), "--role", "frontend",
                      "--row-ids", "ghost", "--status", "review", expect=1)
        self.assertEqual(out["errors"][0]["code"], "unknown_row")


if __name__ == "__main__":
    unittest.main()
