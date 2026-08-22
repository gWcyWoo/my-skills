import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "icps_local.py"


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


class TestIcpsLocal(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.backend = make_backend(self.tmp)

    def _snapshot(self):
        return json.loads(self.backend.read_text())

    def test_inspect_by_status(self):
        rc, out = run("inspect", "--link", str(self.backend), "--role", "frontend",
                      "--status", "ready")
        self.assertEqual(out["row"]["row_id"], "r1")

    def test_inspect_claim_and_writeback(self):
        _, ins = run("inspect", "--link", str(self.backend), "--role", "frontend",
                     "--status", "ready", "--claim", "doing")
        token = ins["lease_token"]
        snap = self._snapshot()
        self.assertTrue(all(r["roles"]["frontend"]["status"] == "doing"
                            for r in snap["rows"] if r["row_id"] == "r1"))
        rc, out = run("claim", "--link", str(self.backend), "--role", "frontend",
                      "--row-ids", "r1", "--status", "review", "--lease-token", token,
                      "--pr", "MR-1")
        snap = self._snapshot()
        cell = next(r for r in snap["rows"] if r["row_id"] == "r1")["roles"]["frontend"]
        self.assertEqual(cell["status"], "review")
        self.assertEqual(cell["pr"], "MR-1")
        self.assertIsNone(cell["lease_token"])

    def test_claim_stale_lease_rejected(self):
        run("inspect", "--link", str(self.backend), "--role", "frontend",
            "--status", "ready", "--claim", "doing")
        rc, out = run("claim", "--link", str(self.backend), "--role", "frontend",
                      "--row-ids", "r1", "--status", "review", "--lease-token", "deadbeef",
                      expect=1)
        self.assertEqual(out["errors"][0]["code"], "stale_lease")

    def test_claim_to_ready_releases_lease_with_error(self):
        _, ins = run("inspect", "--link", str(self.backend), "--role", "frontend",
                     "--status", "ready", "--claim", "doing")
        run("claim", "--link", str(self.backend), "--role", "frontend",
            "--row-ids", "r1", "--status", "ready", "--error", "cookie expired")
        snap = self._snapshot()
        cell = next(r for r in snap["rows"] if r["row_id"] == "r1")["roles"]["frontend"]
        self.assertEqual(cell["status"], "ready")
        self.assertIn("cookie expired", cell["last_error"])
        self.assertIsNone(cell["lease_token"])

    def test_claim_unknown_row_rejected(self):
        rc, out = run("claim", "--link", str(self.backend), "--role", "frontend",
                      "--row-ids", "ghost", "--status", "review", expect=1)
        self.assertEqual(out["errors"][0]["code"], "unknown_row")


if __name__ == "__main__":
    unittest.main()
