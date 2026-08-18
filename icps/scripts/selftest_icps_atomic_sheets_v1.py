#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from icps_atomic_sheets_v1 import AtomicSheetQueue, QueueMapping, SheetRow


class MemorySheetStore:
    def __init__(self, rows: list[SheetRow]) -> None:
        self.rows = rows
        self.status_lookups: list[tuple[str, str]] = []
        self.row_reads: list[int] = []

    def find_first_row_number(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        column: str,
        value: str,
    ) -> int | None:
        self.status_lookups.append((column, value))
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
        self.row_reads.append(row_number)
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


class AtomicSheetQueueTests(unittest.TestCase):
    def test_claims_first_ready_row_with_a_lease(self) -> None:
        store = MemorySheetStore(
            [
                SheetRow(2, {"编号": "A", "状态": "ready"}),
                SheetRow(3, {"编号": "B", "状态": "ready"}),
            ]
        )
        mapping = QueueMapping(
            row_id="编号",
            status="状态",
            lease_token="lease_token",
            lease_until="lease_until",
            pr_url="PR地址",
            ready="ready",
            doing="doing",
            done="done",
        )

        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetQueue(
                store=store,
                lock_root=Path(lock_directory),
                clock=lambda: datetime(2026, 7, 22, 8, 0, tzinfo=timezone.utc),
                token_factory=lambda: "lease-A",
            )
            result = queue.claim("book", "Tasks", mapping, lease_seconds=3600)

        self.assertEqual(result["status"], "claimed")
        self.assertEqual(result["row_number"], 2)
        self.assertEqual(result["row"]["编号"], "A")
        self.assertEqual(result["row"]["状态"], "doing")
        self.assertEqual(result["row"]["lease_token"], "lease-A")
        self.assertEqual(result["row"]["lease_until"], "2026-07-22T09:00:00Z")
        self.assertEqual(store.status_lookups, [("状态", "ready")])
        self.assertEqual(store.row_reads, [2])

    def test_claim_does_not_read_or_validate_unrelated_row_contents(self) -> None:
        store = MemorySheetStore(
            [
                SheetRow(2, {"编号": "unrelated\ninvalid", "状态": "done"}),
                SheetRow(3, {"编号": "B", "状态": "ready"}),
            ]
        )
        mapping = QueueMapping(
            row_id="编号",
            status="状态",
            lease_token="lease_token",
            lease_until="lease_until",
            pr_url="PR地址",
            ready="ready",
            doing="doing",
            done="done",
        )

        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "lease-B",
            )
            result = queue.claim("book", "Tasks", mapping, lease_seconds=3600)

        self.assertEqual(result["row_number"], 3)
        self.assertEqual(result["row"]["编号"], "B")
        self.assertEqual(store.row_reads, [3])

    def test_completes_only_the_matching_leased_row(self) -> None:
        store = MemorySheetStore(
            [
                SheetRow(
                    2,
                    {
                        "编号": "A",
                        "状态": "ready",
                        "lease_token": "",
                        "PR地址": "",
                    },
                )
            ]
        )
        mapping = QueueMapping(
            row_id="编号",
            status="状态",
            lease_token="lease_token",
            lease_until="lease_until",
            pr_url="PR地址",
            ready="ready",
            doing="doing",
            done="done",
        )

        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "lease-A",
            )
            queue.claim("book", "Tasks", mapping, lease_seconds=3600)
            result = queue.complete(
                "book",
                "Tasks",
                mapping,
                row_id="A",
                lease_token="lease-A",
                pr_url="https://github.com/example/repo/pull/1",
            )
            replay = queue.complete(
                "book",
                "Tasks",
                mapping,
                row_id="A",
                lease_token="lease-A",
                pr_url="https://github.com/example/repo/pull/1",
            )

        self.assertEqual(result["status"], "done")
        self.assertEqual(result["row_status"], "done")
        self.assertTrue(replay["reconstructed"])
        self.assertEqual(store.rows[0].values["状态"], "done")
        self.assertEqual(
            store.rows[0].values["PR地址"],
            "https://github.com/example/repo/pull/1",
        )

    def test_rejects_completion_when_the_lease_changed(self) -> None:
        store = MemorySheetStore(
            [
                SheetRow(
                    2,
                    {"编号": "A", "状态": "ready", "lease_token": ""},
                )
            ]
        )
        mapping = QueueMapping(
            row_id="编号",
            status="状态",
            lease_token="lease_token",
            lease_until="lease_until",
            pr_url="PR地址",
            ready="ready",
            doing="doing",
            done="done",
        )

        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "lease-old",
            )
            queue.claim("book", "Tasks", mapping, lease_seconds=3600)
            store.rows[0].values["lease_token"] = "lease-new"
            with self.assertRaisesRegex(ValueError, "lease mismatch"):
                queue.complete(
                    "book",
                    "Tasks",
                    mapping,
                    row_id="A",
                    lease_token="lease-old",
                    pr_url="https://github.com/example/repo/pull/1",
                )

        self.assertEqual(store.rows[0].values["状态"], "doing")
        self.assertNotIn("PR地址", store.rows[0].values)

    def test_completion_without_mr_preserves_pr_value(self) -> None:
        store = MemorySheetStore(
            [
                SheetRow(
                    2,
                    {
                        "编号": "A",
                        "状态": "ready",
                        "lease_token": "",
                        "PR地址": "",
                    },
                )
            ]
        )
        mapping = QueueMapping(
            row_id="编号",
            status="状态",
            lease_token="lease_token",
            lease_until="lease_until",
            pr_url="PR地址",
            ready="ready",
            doing="doing",
            done="review",
        )
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "lease-A",
            )
            queue.claim("book", "Tasks", mapping, lease_seconds=3600)
            result = queue.complete(
                "book",
                "Tasks",
                mapping,
                row_id="A",
                lease_token="lease-A",
                pr_url=None,
            )

        self.assertEqual(result["row_status"], "review")
        self.assertEqual(store.rows[0].values["状态"], "review")
        self.assertEqual(store.rows[0].values["PR地址"], "")


if __name__ == "__main__":
    unittest.main()
