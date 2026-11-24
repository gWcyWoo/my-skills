"""Public lease contract shared by ICPS and ICPL, using real locked files/processes."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = [ROOT / "icps/scripts/icps_local.py", ROOT / "icpl/scripts/icpl.py"]


class LeaseMaintenance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="owned-lease-contract-")
        self.path = Path(self.temp.name) / "source.json"

    def tearDown(self):
        self.temp.cleanup()

    def seed(self, live=False):
        deadline = (datetime.now(timezone.utc) + timedelta(minutes=5) if live else
                    datetime.now(timezone.utc) - timedelta(hours=40)).isoformat()
        self.doc = {"schema": "iole-item.sheet", "metadata": "retain", "rows": [
            {"row_id": "r7", "payload": {"design": "frozen"}, "roles": {
                "frontend": {"status": "doing", "lease_token": "owned-token", "lease_until": deadline,
                             "pr": "existing-pr", "reviews": "retain", "last_error": "previous evidence"},
                "backend": {"status": "doing", "lease_token": "other-role"}}},
            {"row_id": "r8", "payload": {}, "roles": {"frontend": {"status": "ready"}}}]}
        self.path.write_text(json.dumps(self.doc))
        return {"row-id": "r7", "role": "frontend", "lease-token": "owned-token",
                "expected-lease-until": deadline, "lease-minutes": "60"}

    def command(self, script, verb, args):
        return [sys.executable, str(script), verb, "--link", str(self.path),
                *[part for key, value in args.items() for part in ("--" + key, value)]]

    def invoke(self, script, verb, args, code=0):
        result = subprocess.run(self.command(script, verb, args), capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_renew_extends_live_deadline_without_changing_identity_or_other_data(self):
        for script in SCRIPTS:
            with self.subTest(adapter=script):
                args = self.seed(live=True)
                result = self.invoke(script, "renew", args)
                expected = copy.deepcopy(self.doc)
                expected["rows"][0]["roles"]["frontend"]["lease_until"] = result["lease_until"]
                self.assertEqual(json.loads(self.path.read_text()), expected)
                self.assertEqual(result["lease_token"], "owned-token")
                self.assertGreater(datetime.fromisoformat(result["lease_until"]), datetime.fromisoformat(args["expected-lease-until"]))
                unchanged = self.path.read_bytes()
                self.assertEqual(self.invoke(script, "renew", args, 1)["errors"][0]["code"], "lease_version_changed")
                self.assertEqual(self.path.read_bytes(), unchanged)

    def test_recovery_rotates_expired_identity_without_resetting_status_or_evidence(self):
        for script in SCRIPTS:
            with self.subTest(adapter=script):
                args = self.seed()
                start = datetime.now(timezone.utc)
                result = self.invoke(script, "recover", args)
                expected = copy.deepcopy(self.doc)
                expected["rows"][0]["roles"]["frontend"].update(lease_token=result["lease_token"], lease_until=result["lease_until"])
                self.assertEqual(json.loads(self.path.read_text()), expected)
                self.assertNotEqual(result["lease_token"], "owned-token")
                self.assertGreaterEqual(datetime.fromisoformat(result["lease_until"]), start + timedelta(minutes=60))
                self.assertLessEqual(datetime.fromisoformat(result["lease_until"]), datetime.now(timezone.utc) + timedelta(minutes=60))
                unchanged = self.path.read_bytes()
                self.invoke(script, "recover", args, 1)
                old = subprocess.run([sys.executable, str(script), "claim", "--link", str(self.path),
                                      "--role", "frontend", "--row-ids", "r7", "--status", "review",
                                      "--lease-token", "owned-token"], capture_output=True, text=True)
                self.assertEqual(old.returncode, 1)
                self.assertEqual(json.loads(old.stdout)["errors"][0]["code"], "stale_lease")
                self.assertEqual(self.path.read_bytes(), unchanged)

    def test_rejections_leave_the_entire_canonical_unchanged(self):
        cases = ["foreign_token", "changed_deadline", "ready", "review", "missing_deadline",
                 "malformed_deadline", "naive_deadline", "unknown_row", "unknown_role", "empty_token",
                 "zero_duration", "negative_duration", "overflow_duration", "live_recovery", "expired_renewal"]
        for script in SCRIPTS:
            for case in cases:
                with self.subTest(adapter=script, case=case):
                    args = self.seed(live=case == "live_recovery")
                    cell = self.doc["rows"][0]["roles"]["frontend"]
                    if case == "foreign_token": args["lease-token"] = "foreign"
                    elif case == "changed_deadline": cell["lease_until"] = "2020-01-01T00:00:00+00:00"
                    elif case in ("ready", "review"): cell["status"] = case
                    elif case == "missing_deadline": cell["lease_until"] = None
                    elif case in ("malformed_deadline", "naive_deadline"):
                        cell["lease_until"] = args["expected-lease-until"] = "broken" if case == "malformed_deadline" else "2020-01-01T00:00:00"
                    elif case == "unknown_row": args["row-id"] = "missing"
                    elif case == "unknown_role": args["role"] = "missing"
                    elif case == "empty_token": args["lease-token"] = ""
                    elif case == "zero_duration": args["lease-minutes"] = "0"
                    elif case == "negative_duration": args["lease-minutes"] = "-1"
                    elif case == "overflow_duration": args["lease-minutes"] = str(10 ** 20)
                    self.path.write_text(json.dumps(self.doc))
                    unchanged = self.path.read_bytes()
                    result = self.invoke(script, "renew" if case == "expired_renewal" else "recover", args, 1)
                    self.assertFalse(result["ok"])
                    self.assertEqual(self.path.read_bytes(), unchanged)
                    self.assertFalse(self.path.with_suffix(".json.lock").exists())

    def test_concurrent_same_version_has_one_winner_for_both_operations(self):
        for script in SCRIPTS:
            for verb in ("renew", "recover"):
                with self.subTest(adapter=script, operation=verb):
                    args = self.seed(live=verb == "renew")
                    children = [subprocess.Popen(self.command(script, verb, args), stdout=subprocess.PIPE,
                                                stderr=subprocess.PIPE, text=True) for _ in range(2)]
                    outputs = [p.communicate(timeout=10) for p in children]
                    self.assertEqual(sorted(p.returncode for p in children), [0, 1], outputs)
                    winner = next(json.loads(out[0]) for p, out in zip(children, outputs) if p.returncode == 0)
                    cell = json.loads(self.path.read_text())["rows"][0]["roles"]["frontend"]
                    self.assertEqual((cell["lease_token"], cell["lease_until"]), (winner["lease_token"], winner["lease_until"]))


if __name__ == "__main__":
    unittest.main()
