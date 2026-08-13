#!/usr/bin/env python3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ICPS_SCRIPTS = Path(__file__).parents[2] / "icps" / "scripts"
sys.path.insert(0, str(ICPS_SCRIPTS))

from icps_atomic_sheets_v1 import (
    AtomicSheetQueue,
    QueueMapping,
    SheetRow,
    canonical_row_id,
)


class MemorySheetStore:
    def __init__(self, rows: list[SheetRow]) -> None:
        self.rows = rows

    def find_first_row_number(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        column: str,
        value: str,
    ) -> int | None:
        return next(
            (row.row_number for row in self.rows if row.values.get(column) == value),
            None,
        )

    def read_row(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        row_number: int,
    ) -> SheetRow:
        for row in self.rows:
            if row.row_number == row_number:
                return SheetRow(row.row_number, dict(row.values))
        raise ValueError("row not found")

    def update_row(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        row_number: int,
        updates: dict[str, str],
    ) -> SheetRow:
        for row in self.rows:
            if row.row_number == row_number:
                row.values.update(updates)
                return SheetRow(row.row_number, dict(row.values))
        raise ValueError("row not found")


class IoleAtomicRoleTests(unittest.TestCase):
    def test_row_identity_rejects_control_characters(self) -> None:
        with self.assertRaisesRegex(ValueError, "control characters"):
            canonical_row_id("4\n2")

    def test_completion_rejects_immutable_row_drift(self) -> None:
        row = SheetRow(
            2,
            {
                "编号": "42",
                "frontend status": "ready",
                "frontend lease_token": "",
                "frontend lease_until": "",
                "frontend pr": "",
                "frontend last_error": "previous failure",
                "UI补充描述": "old requirement",
            },
        )
        store = MemorySheetStore([row])
        mapping = QueueMapping(
            row_id="编号",
            status="frontend status",
            lease_token="frontend lease_token",
            lease_until="frontend lease_until",
            pr_url="frontend pr",
            ready="ready",
            doing="doing",
            done="review",
            last_error="frontend last_error",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            queue = AtomicSheetQueue(
                store,
                Path(temporary_directory),
                token_factory=lambda: "client-token",
                clock=lambda: datetime(2026, 7, 23, 10, 0, tzinfo=timezone.utc),
            )
            queue.claim("book", "Sheet1", mapping, lease_seconds=600)
            self.assertEqual(row.values["frontend last_error"], "")
            queue.record_error(
                "book",
                "Sheet1",
                mapping,
                row_id="42",
                lease_token="client-token",
                error_code="worker/page-verification-failed",
                expected_values={"UI补充描述": "old requirement"},
            )
            self.assertEqual(
                row.values["frontend last_error"],
                "worker/page-verification-failed",
            )
            row.values["UI补充描述"] = "changed requirement"
            with self.assertRaisesRegex(ValueError, "row input drift"):
                queue.complete(
                    "book",
                    "Sheet1",
                    mapping,
                    row_id="42",
                    lease_token="client-token",
                    pr_url="https://gitlab.example/client/merge_requests/8",
                    expected_values={
                        "UI补充描述": "old requirement",
                        "frontend pr": "",
                    },
                )

        self.assertEqual(row.values["frontend status"], "doing")
        self.assertEqual(row.values["frontend pr"], "")

    def test_client_and_backend_claim_the_same_row_with_independent_leases(self) -> None:
        row = SheetRow(
            2,
            {
                "编号": "42",
                "frontend status": "ready",
                "frontend lease_token": "",
                "frontend lease_until": "",
                "frontend pr": "",
                "backend status": "ready",
                "backend lease_token": "",
                "backend lease_until": "",
                "backend pr": "",
            },
        )
        store = MemorySheetStore([row])
        client = QueueMapping(
            row_id="编号",
            status="frontend status",
            lease_token="frontend lease_token",
            lease_until="frontend lease_until",
            pr_url="frontend pr",
            ready="ready",
            doing="doing",
            done="review",
        )
        backend = QueueMapping(
            row_id="编号",
            status="backend status",
            lease_token="backend lease_token",
            lease_until="backend lease_until",
            pr_url="backend pr",
            ready="ready",
            doing="doing",
            done="review",
        )
        tokens = iter(["client-lease", "backend-lease"])

        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetQueue(
                store=store,
                lock_root=Path(lock_directory),
                clock=lambda: datetime(2026, 7, 23, 8, 0, tzinfo=timezone.utc),
                token_factory=lambda: next(tokens),
            )
            queue.claim("book", "Tasks", client, lease_seconds=3600)
            queue.claim("book", "Tasks", backend, lease_seconds=3600)
            queue.complete(
                "book",
                "Tasks",
                client,
                row_id="42",
                lease_token="client-lease",
                pr_url="https://git.example/client/merge_requests/1",
            )
            queue.complete(
                "book",
                "Tasks",
                backend,
                row_id="42",
                lease_token="backend-lease",
                pr_url="http://git.example/backend/merge_requests/2",
            )

        self.assertEqual(row.values["frontend status"], "review")
        self.assertEqual(row.values["backend status"], "review")
        self.assertEqual(row.values["frontend lease_token"], "")
        self.assertEqual(row.values["frontend lease_until"], "")
        self.assertEqual(row.values["backend lease_token"], "")
        self.assertEqual(row.values["backend lease_until"], "")
        self.assertEqual(
            row.values["frontend pr"],
            "https://git.example/client/merge_requests/1",
        )
        self.assertEqual(
            row.values["backend pr"],
            "http://git.example/backend/merge_requests/2",
        )

    def test_claim_ignores_unrelated_duplicate_row_identities(self) -> None:
        rows = [
            SheetRow(2, {"编号": "42", "frontend status": "review"}),
            SheetRow(3, {"编号": "42", "frontend status": "review"}),
            SheetRow(
                4,
                {
                    "编号": "43",
                    "frontend status": "ready",
                    "frontend lease_token": "",
                    "frontend lease_until": "",
                    "frontend pr": "",
                },
            ),
        ]
        mapping = QueueMapping(
            row_id="编号",
            status="frontend status",
            lease_token="frontend lease_token",
            lease_until="frontend lease_until",
            pr_url="frontend pr",
            ready="ready",
            doing="doing",
            done="review",
        )
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetQueue(
                store=MemorySheetStore(rows),
                lock_root=Path(lock_directory),
                token_factory=lambda: "client-lease",
            )
            result = queue.claim("book", "Tasks", mapping, lease_seconds=3600)

        self.assertEqual(result["row_number"], 4)
        self.assertEqual(result["row"]["编号"], "43")

    def test_completion_rejects_a_non_http_pr_url(self) -> None:
        row = SheetRow(
            2,
            {
                "编号": "42",
                "frontend status": "ready",
                "frontend lease_token": "",
                "frontend lease_until": "2026-07-23T09:00:00Z",
                "frontend pr": "",
            },
        )
        mapping = QueueMapping(
            row_id="编号",
            status="frontend status",
            lease_token="frontend lease_token",
            lease_until="frontend lease_until",
            pr_url="frontend pr",
            ready="ready",
            doing="doing",
            done="review",
        )
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetQueue(
                store=MemorySheetStore([row]),
                lock_root=Path(lock_directory),
            )
            with self.assertRaisesRegex(ValueError, "HTTP or HTTPS"):
                queue.complete(
                    "book",
                    "Tasks",
                    mapping,
                    row_id="42",
                    lease_token="client-lease",
                    pr_url="file:///tmp/not-a-pr",
                )

    def test_numeric_sheet_identity_matches_the_canonical_string_claim(self) -> None:
        row = SheetRow(
            2,
            {
                "编号": 42,
                "frontend status": "ready",
                "frontend lease_token": "",
                "frontend lease_until": "",
                "frontend pr": "",
            },
        )
        mapping = QueueMapping(
            row_id="编号",
            status="frontend status",
            lease_token="frontend lease_token",
            lease_until="frontend lease_until",
            pr_url="frontend pr",
            ready="ready",
            doing="doing",
            done="review",
        )
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetQueue(
                store=MemorySheetStore([row]),
                lock_root=Path(lock_directory),
                token_factory=lambda: "client-lease",
            )
            queue.claim("book", "Tasks", mapping, lease_seconds=3600)
            result = queue.complete(
                "book",
                "Tasks",
                mapping,
                row_id="42",
                lease_token="client-lease",
                pr_url="https://git.example/client/merge_requests/1",
            )

        self.assertEqual(result["status"], "done")
        self.assertEqual(row.values["frontend status"], "review")


if __name__ == "__main__":
    unittest.main()
