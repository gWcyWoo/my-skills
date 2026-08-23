#!/usr/bin/env python3
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import icps_atomic_sheets_v2 as flow_module
from icps_atomic_sheets_v1 import SheetRow
from icps_atomic_sheets_v2 import AtomicSheetFlowQueue, FlowQueueMapping


class MemoryFlowSheetStore:
    def __init__(self, rows: list[SheetRow]) -> None:
        self.rows = rows
        self.batch_updates: list[dict[int, dict[str, str]]] = []

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

    def find_row_numbers_by_value(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        column: str,
        value: str,
    ) -> list[int]:
        return [
            row.row_number for row in self.rows if row.values.get(column) == value
        ]

    def read_row(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        row_number: int,
    ) -> SheetRow:
        return self.read_rows(spreadsheet_id, sheet_name, [row_number])[0]

    def find_row_numbers_by_ids(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        column: str,
        row_ids: list[str],
    ) -> dict[str, int]:
        requested = set(row_ids)
        return {
            str(row.values.get(column)): row.row_number
            for row in self.rows
            if row.values.get(column) in requested
        }

    def list_row_ids(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        column: str,
    ) -> list[str]:
        return [
            str(row.values.get(column)).strip()
            for row in self.rows
            if str(row.values.get(column, "")).strip()
        ]

    def read_rows(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        row_numbers: list[int],
    ) -> list[SheetRow]:
        by_number = {row.row_number: row for row in self.rows}
        return [
            SheetRow(number, dict(by_number[number].values)) for number in row_numbers
        ]

    def update_rows(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        updates: dict[int, dict[str, str]],
    ) -> list[SheetRow]:
        self.batch_updates.append(
            {number: dict(values) for number, values in updates.items()}
        )
        by_number = {row.row_number: row for row in self.rows}
        for row_number, row_updates in updates.items():
            by_number[row_number].values.update(row_updates)
        return self.read_rows(spreadsheet_id, sheet_name, list(updates))


class LostResponseFlowSheetStore(MemoryFlowSheetStore):
    def __init__(self, rows: list[SheetRow]) -> None:
        super().__init__(rows)
        self.lose_next_update_response = False

    def update_rows(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        updates: dict[int, dict[str, str]],
    ) -> list[SheetRow]:
        result = super().update_rows(spreadsheet_id, sheet_name, updates)
        if self.lose_next_update_response:
            self.lose_next_update_response = False
            raise RuntimeError("simulated lost response")
        return result


class FailBeforeUpdateFlowSheetStore(MemoryFlowSheetStore):
    def __init__(self, rows: list[SheetRow]) -> None:
        super().__init__(rows)
        self.fail_next_update = False

    def update_rows(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        updates: dict[int, dict[str, str]],
    ) -> list[SheetRow]:
        if self.fail_next_update:
            self.fail_next_update = False
            raise RuntimeError("simulated pre-write failure")
        return super().update_rows(spreadsheet_id, sheet_name, updates)


class DriftAfterUpdateFlowSheetStore(MemoryFlowSheetStore):
    def __init__(self, rows: list[SheetRow]) -> None:
        super().__init__(rows)
        self.drift_next_update = False

    def update_rows(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        updates: dict[int, dict[str, str]],
    ) -> list[SheetRow]:
        super().update_rows(spreadsheet_id, sheet_name, updates)
        if self.drift_next_update:
            self.drift_next_update = False
            self.rows[1].values.update(
                {
                    "frontend status": "doing",
                    "frontend lease_token": "other-worker",
                    "frontend lease_until": "later",
                }
            )
        return self.read_rows(spreadsheet_id, sheet_name, list(updates))


def mapping() -> FlowQueueMapping:
    return FlowQueueMapping(
        row_id="编号",
        status="frontend status",
        lease_token="frontend lease_token",
        lease_until="frontend lease_until",
        pr_url="frontend pr",
        last_error="frontend last_error",
        ready="ready",
        doing="doing",
        review="review",
        done="done",
    )


def ready_rows() -> list[SheetRow]:
    return [
        SheetRow(
            number,
            {
                "编号": page_id,
                "标题": title,
                "frontend status": "ready",
                "frontend pr": "",
                "frontend lease_token": "",
                "frontend lease_until": "",
                "frontend last_error": "",
            },
        )
        for number, page_id, title in (
            (2, "PAGE-001", "申请首页"),
            (3, "PAGE-002", "职业信息页"),
            (4, "PAGE-003", "申请结果页"),
        )
    ]


def guards(*row_ids: str) -> dict[str, dict[str, object]]:
    titles = {
        "PAGE-001": "申请首页",
        "PAGE-002": "职业信息页",
        "PAGE-003": "申请结果页",
    }
    return {
        row_id: {"标题": titles[row_id], "frontend pr": ""}
        for row_id in row_ids
    }


class AtomicSheetFlowQueueTests(unittest.TestCase):
    def test_active_claim_inspection_fails_closed_on_corrupt_locator(self) -> None:
        store = MemoryFlowSheetStore(ready_rows()[:1])
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
            )
            locator_path = queue._locator_path(
                "book",
                "Tasks",
                "iole-flow-abc",
            )
            locator_path.parent.mkdir(parents=True, exist_ok=True)
            locator_path.write_text("{not-json\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "active flow locator is unreadable"):
                queue.inspect_active_flow_claims("book", "Tasks", mapping())

    def test_active_claim_inspection_excludes_released_history(self) -> None:
        store = MemoryFlowSheetStore(ready_rows()[:1])
        expected_values = guards("PAGE-001")
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            claimed = queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001"],
                lease_seconds=3600,
                expected_values=expected_values,
            )
            queue.release_flow_claim(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                lease_token=claimed["lease_token"],
                expected_values=expected_values,
            )

            inspection = queue.inspect_active_flow_claims(
                "book", "Tasks", mapping()
            )

        self.assertEqual(inspection["kind"], "icps.active-flow-claims.v1")
        self.assertEqual(inspection["status"], "none")
        self.assertEqual(inspection["claims"], [])

    def test_active_claim_inspection_returns_only_the_current_lease(self) -> None:
        store = MemoryFlowSheetStore(ready_rows()[:1])
        expected_values = guards("PAGE-001")
        lease_tokens = iter(["flow-lease-1", "flow-lease-2"])
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                clock=lambda: datetime(2026, 8, 20, 9, 1, 3, tzinfo=timezone.utc),
                token_factory=lambda: next(lease_tokens),
            )
            first_claim = queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001"],
                lease_seconds=3600,
                expected_values=expected_values,
            )
            queue.release_flow_claim(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                lease_token=first_claim["lease_token"],
                expected_values=expected_values,
            )
            queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001"],
                lease_seconds=3600,
                expected_values=expected_values,
            )

            inspection = queue.inspect_active_flow_claims(
                "book", "Tasks", mapping()
            )

        self.assertEqual(inspection["status"], "active")
        self.assertEqual(
            inspection["claims"],
            [
                {
                    "flow_id": "iole-flow-abc",
                    "lease_token": "flow-lease-2",
                    "lease_until": "2026-08-20T10:01:03Z",
                    "phase": "claimed",
                    "member_row_ids": ["PAGE-001"],
                }
            ],
        )

    def test_active_claim_inspection_rejects_stale_live_locator(self) -> None:
        rows = ready_rows()[:1]
        store = MemoryFlowSheetStore(rows)
        expected_values = guards("PAGE-001")
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001"],
                lease_seconds=3600,
                expected_values=expected_values,
            )
            rows[0].values.update(
                {
                    "frontend status": "doing",
                    "frontend lease_token": "new-lease",
                    "frontend lease_until": "2099-01-01T00:00:00Z",
                }
            )

            with self.assertRaisesRegex(ValueError, "active flow member state drift"):
                queue.inspect_active_flow_claims("book", "Tasks", mapping())

    def test_active_claim_inspection_rejects_partial_pending_expansion(self) -> None:
        rows = ready_rows()
        store = MemoryFlowSheetStore(rows)
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001"],
                lease_seconds=3600,
                expected_values=guards("PAGE-001"),
            )
            locator = queue._load_locator("book", "Tasks", "iole-flow-abc")
            queue._replace_locator(
                "book",
                "Tasks",
                "iole-flow-abc",
                {
                    **locator,
                    "pending_expansion": [
                        {"row_id": "PAGE-002", "row_number": 3},
                        {"row_id": "PAGE-003", "row_number": 4},
                    ],
                    "pending_guard_digests": queue._guard_digests(
                        guards("PAGE-002", "PAGE-003")
                    ),
                },
            )
            rows[1].values.update(
                {
                    "frontend status": "doing",
                    "frontend lease_token": locator["lease_token"],
                    "frontend lease_until": locator["lease_until"],
                }
            )

            with self.assertRaisesRegex(
                ValueError,
                "active flow pending expansion is partially claimed",
            ):
                queue.inspect_active_flow_claims("book", "Tasks", mapping())

    def test_active_claim_inspection_reports_ready_pending_expansion(self) -> None:
        rows = ready_rows()[:2]
        store = MemoryFlowSheetStore(rows)
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001"],
                lease_seconds=3600,
                expected_values=guards("PAGE-001"),
            )
            locator = queue._load_locator("book", "Tasks", "iole-flow-abc")
            queue._replace_locator(
                "book",
                "Tasks",
                "iole-flow-abc",
                {
                    **locator,
                    "pending_expansion": [
                        {"row_id": "PAGE-002", "row_number": 3},
                    ],
                    "pending_guard_digests": queue._guard_digests(
                        guards("PAGE-002")
                    ),
                },
            )

            inspection = queue.inspect_active_flow_claims(
                "book", "Tasks", mapping()
            )

        self.assertEqual(
            inspection["claims"][0]["pending_member_row_ids"],
            ["PAGE-002"],
        )
        self.assertEqual(inspection["claims"][0]["pending_state"], "ready")

    def test_active_claim_inspection_reports_claimed_pending_expansion(self) -> None:
        rows = ready_rows()[:2]
        store = MemoryFlowSheetStore(rows)
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001"],
                lease_seconds=3600,
                expected_values=guards("PAGE-001"),
            )
            locator = queue._load_locator("book", "Tasks", "iole-flow-abc")
            queue._replace_locator(
                "book",
                "Tasks",
                "iole-flow-abc",
                {
                    **locator,
                    "pending_expansion": [
                        {"row_id": "PAGE-002", "row_number": 3},
                    ],
                    "pending_guard_digests": queue._guard_digests(
                        guards("PAGE-002")
                    ),
                },
            )
            rows[1].values.update(
                {
                    "frontend status": "doing",
                    "frontend lease_token": locator["lease_token"],
                    "frontend lease_until": locator["lease_until"],
                }
            )

            inspection = queue.inspect_active_flow_claims(
                "book", "Tasks", mapping()
            )

        self.assertEqual(
            inspection["claims"][0]["pending_member_row_ids"],
            ["PAGE-002"],
        )
        self.assertEqual(inspection["claims"][0]["pending_state"], "claimed")

    def test_active_claim_inspection_reports_recoverable_prepared_claim(self) -> None:
        store = FailBeforeUpdateFlowSheetStore(ready_rows()[:1])
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            store.fail_next_update = True
            with self.assertRaisesRegex(RuntimeError, "simulated pre-write failure"):
                queue.claim_flow(
                    "book",
                    "Tasks",
                    mapping(),
                    flow_id="iole-flow-abc",
                    row_ids=["PAGE-001"],
                    lease_seconds=3600,
                    expected_values=guards("PAGE-001"),
                )

            inspection = queue.inspect_active_flow_claims(
                "book", "Tasks", mapping()
            )

        self.assertEqual(inspection["status"], "active")
        self.assertEqual(inspection["claims"][0]["phase"], "claim-prepared")
        self.assertEqual(
            inspection["claims"][0]["member_row_ids"],
            ["PAGE-001"],
        )

    def test_releases_claimed_flow_and_allows_a_fresh_claim(self) -> None:
        rows = ready_rows()
        rows[0].values["业务字段"] = "保留"
        rows[0].values["backend status"] = "doing"
        rows[0].values["backend lease_token"] = "backend-lease"
        store = MemoryFlowSheetStore(rows)
        lease_tokens = iter(["flow-lease-1", "flow-lease-2"])
        all_guards = guards("PAGE-001", "PAGE-002", "PAGE-003")
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                clock=lambda: datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc),
                token_factory=lambda: next(lease_tokens),
            )
            claimed = queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001", "PAGE-002", "PAGE-003"],
                lease_seconds=3600,
                expected_values=all_guards,
            )
            queue.record_flow_error(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                lease_token=claimed["lease_token"],
                error_code="worker/node-failed",
                expected_values=all_guards,
            )

            released = queue.release_flow_claim(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                lease_token="flow-lease-1",
                expected_values=all_guards,
            )

            self.assertEqual(released["status"], "released")
            self.assertFalse(released["reconstructed"])
            self.assertEqual(
                released["member_row_ids"],
                ["PAGE-001", "PAGE-002", "PAGE-003"],
            )
            for row in store.rows:
                self.assertEqual(row.values["frontend status"], "ready")
                self.assertEqual(row.values["frontend pr"], "")
                self.assertEqual(row.values["frontend lease_token"], "")
                self.assertEqual(row.values["frontend lease_until"], "")
                self.assertEqual(row.values["frontend last_error"], "")
            self.assertEqual(store.rows[0].values["业务字段"], "保留")
            self.assertEqual(store.rows[0].values["backend status"], "doing")
            self.assertEqual(
                store.rows[0].values["backend lease_token"], "backend-lease"
            )

            restarted = queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001", "PAGE-002", "PAGE-003"],
                lease_seconds=3600,
                expected_values=all_guards,
            )

        self.assertEqual(restarted["status"], "claimed")
        self.assertEqual(restarted["lease_token"], "flow-lease-2")
        self.assertFalse(restarted["reconstructed"])
        self.assertTrue(
            all(row.values["frontend status"] == "doing" for row in store.rows)
        )

    def test_releases_a_claim_whose_members_were_already_reset_to_ready(self) -> None:
        store = MemoryFlowSheetStore(ready_rows())
        lease_tokens = iter(["flow-lease-1", "flow-lease-2"])
        all_guards = guards("PAGE-001", "PAGE-002", "PAGE-003")
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: next(lease_tokens),
            )
            queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001", "PAGE-002", "PAGE-003"],
                lease_seconds=3600,
                expected_values=all_guards,
            )
            for row in store.rows:
                row.values.update(
                    {
                        "frontend status": "ready",
                        "frontend lease_token": "",
                        "frontend lease_until": "",
                        "frontend last_error": "",
                    }
                )

            released = queue.release_flow_claim(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                lease_token="flow-lease-1",
                expected_values=all_guards,
            )
            restarted = queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001", "PAGE-002", "PAGE-003"],
                lease_seconds=3600,
                expected_values=all_guards,
            )

        self.assertEqual(released["status"], "released")
        self.assertEqual(restarted["lease_token"], "flow-lease-2")
        self.assertEqual(len(store.batch_updates), 2)

    def test_releases_mixed_members_that_still_belong_to_the_same_claim(self) -> None:
        store = MemoryFlowSheetStore(ready_rows())
        all_guards = guards("PAGE-001", "PAGE-002", "PAGE-003")
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001", "PAGE-002", "PAGE-003"],
                lease_seconds=3600,
                expected_values=all_guards,
            )
            store.rows[1].values.update(
                {
                    "frontend status": "ready",
                    "frontend lease_token": "",
                    "frontend lease_until": "",
                }
            )
            store.rows[2].values.update(
                {
                    "frontend status": "ready",
                    "frontend last_error": "verification/visual-mismatch",
                }
            )

            released = queue.release_flow_claim(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                lease_token="flow-lease-1",
                expected_values=all_guards,
            )

        self.assertEqual(released["status"], "released")
        self.assertEqual(len(store.batch_updates), 2)
        self.assertEqual(set(store.batch_updates[1]), {2, 3, 4})
        for row in store.rows:
            self.assertEqual(row.values["frontend status"], "ready")
            self.assertEqual(row.values["frontend lease_token"], "")
            self.assertEqual(row.values["frontend lease_until"], "")
            self.assertEqual(row.values["frontend last_error"], "")

    def test_reconstructs_a_released_flow_when_the_response_was_lost(self) -> None:
        store = MemoryFlowSheetStore(ready_rows())
        all_guards = guards("PAGE-001", "PAGE-002", "PAGE-003")
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001", "PAGE-002", "PAGE-003"],
                lease_seconds=3600,
                expected_values=all_guards,
            )
            queue.release_flow_claim(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                lease_token="flow-lease-1",
                expected_values=all_guards,
            )

            reconstructed = queue.release_flow_claim(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                lease_token="flow-lease-1",
                expected_values=all_guards,
            )

        self.assertEqual(reconstructed["status"], "released")
        self.assertTrue(reconstructed["reconstructed"])
        self.assertEqual(len(store.batch_updates), 2)
        self.assertTrue(
            all(row.values["frontend status"] == "ready" for row in store.rows)
        )

    def test_delayed_release_retry_does_not_inspect_rows_owned_by_a_new_flow(self) -> None:
        store = MemoryFlowSheetStore(ready_rows()[:1])
        expected_values = guards("PAGE-001")
        tokens = iter(("old-lease", "new-lease"))
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: next(tokens),
            )
            queue.claim_flow(
                "book", "Tasks", mapping(), "old-flow", ["PAGE-001"], 3600,
                expected_values,
            )
            queue.release_flow_claim(
                "book", "Tasks", mapping(), "old-flow", "old-lease",
                expected_values,
            )
            queue.claim_flow(
                "book", "Tasks", mapping(), "new-flow", ["PAGE-001"], 3600,
                expected_values,
            )

            reconstructed = queue.release_flow_claim(
                "book", "Tasks", mapping(), "old-flow", "old-lease",
                expected_values,
            )

        self.assertTrue(reconstructed["reconstructed"])
        self.assertEqual(store.rows[0].values["frontend lease_token"], "new-lease")

    def test_reconstructs_release_after_the_sheet_update_response_was_lost(self) -> None:
        store = LostResponseFlowSheetStore(ready_rows())
        all_guards = guards("PAGE-001", "PAGE-002", "PAGE-003")
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001", "PAGE-002", "PAGE-003"],
                lease_seconds=3600,
                expected_values=all_guards,
            )
            store.lose_next_update_response = True
            with self.assertRaisesRegex(RuntimeError, "simulated lost response"):
                queue.release_flow_claim(
                    "book",
                    "Tasks",
                    mapping(),
                    flow_id="iole-flow-abc",
                    lease_token="flow-lease-1",
                    expected_values=all_guards,
                )

            reconstructed = queue.release_flow_claim(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                lease_token="flow-lease-1",
                expected_values=all_guards,
            )

        self.assertEqual(reconstructed["status"], "released")
        self.assertTrue(reconstructed["reconstructed"])
        self.assertEqual(len(store.batch_updates), 2)

    def test_release_persists_intent_before_sheet_mutation_and_retry_uses_it(self) -> None:
        store = MemoryFlowSheetStore(ready_rows()[:1])
        expected_values = guards("PAGE-001")
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            queue.claim_flow(
                "book", "Tasks", mapping(), "iole-flow-abc", ["PAGE-001"],
                3600, expected_values,
            )
            with patch.object(
                store, "update_rows", side_effect=RuntimeError("before sheet mutation")
            ):
                with self.assertRaisesRegex(RuntimeError, "before sheet mutation"):
                    queue.release_flow_claim(
                        "book", "Tasks", mapping(), "iole-flow-abc",
                        "flow-lease-1", expected_values,
                    )

            inspection = queue.inspect_active_flow_claims(
                "book", "Tasks", mapping()
            )
            recovered = queue.release_flow_claim(
                "book", "Tasks", mapping(), "iole-flow-abc",
                "flow-lease-1", expected_values,
            )

        self.assertEqual(inspection["claims"][0]["phase"], "release-prepared")
        self.assertEqual(inspection["claims"][0]["release_state"], "prepared")
        self.assertEqual(recovered["status"], "released")
        self.assertTrue(recovered["reconstructed"] is False)

    def test_release_retry_recovers_after_sheet_mutation_before_terminal_locator(self) -> None:
        store = MemoryFlowSheetStore(ready_rows()[:1])
        expected_values = guards("PAGE-001")
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            queue.claim_flow(
                "book", "Tasks", mapping(), "iole-flow-abc", ["PAGE-001"],
                3600, expected_values,
            )
            real_replace_locator = queue._replace_locator
            def interrupt_terminal_locator(*args, **kwargs):
                locator = args[-1]
                if locator.get("phase") == "released":
                    raise RuntimeError("after sheet mutation")
                return real_replace_locator(*args, **kwargs)

            with patch.object(
                queue, "_replace_locator", side_effect=interrupt_terminal_locator
            ):
                with self.assertRaisesRegex(RuntimeError, "after sheet mutation"):
                    queue.release_flow_claim(
                        "book", "Tasks", mapping(), "iole-flow-abc",
                        "flow-lease-1", expected_values,
                    )

            inspection = queue.inspect_active_flow_claims(
                "book", "Tasks", mapping()
            )
            recovered = queue.release_flow_claim(
                "book", "Tasks", mapping(), "iole-flow-abc",
                "flow-lease-1", expected_values,
            )

        self.assertEqual(inspection["claims"][0]["phase"], "release-prepared")
        self.assertEqual(inspection["claims"][0]["release_state"], "terminal")
        self.assertTrue(recovered["reconstructed"])

    def test_release_rejects_a_member_owned_by_another_lease_without_mutation(self) -> None:
        store = MemoryFlowSheetStore(ready_rows())
        all_guards = guards("PAGE-001", "PAGE-002", "PAGE-003")
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001", "PAGE-002", "PAGE-003"],
                lease_seconds=3600,
                expected_values=all_guards,
            )
            store.rows[1].values["frontend lease_token"] = "other-worker"

            with self.assertRaisesRegex(
                ValueError,
                "flow member is not owned by release lease",
            ):
                queue.release_flow_claim(
                    "book",
                    "Tasks",
                    mapping(),
                    flow_id="iole-flow-abc",
                    lease_token="flow-lease-1",
                    expected_values=all_guards,
                )

        self.assertEqual(len(store.batch_updates), 1)
        self.assertTrue(
            all(row.values["frontend status"] == "doing" for row in store.rows)
        )

    def test_finishes_archiving_a_release_interrupted_after_sheet_restore(self) -> None:
        store = MemoryFlowSheetStore(ready_rows())
        all_guards = guards("PAGE-001", "PAGE-002", "PAGE-003")
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001", "PAGE-002", "PAGE-003"],
                lease_seconds=3600,
                expected_values=all_guards,
            )
            queue.release_flow_claim(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                lease_token="flow-lease-1",
                expected_values=all_guards,
            )
            active_path = queue._locator_path("book", "Tasks", "iole-flow-abc")
            archive_path = queue._released_locator_path(
                "book",
                "Tasks",
                "iole-flow-abc",
                "flow-lease-1",
            )
            os.replace(archive_path, active_path)

            reconstructed = queue.release_flow_claim(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                lease_token="flow-lease-1",
                expected_values=all_guards,
            )
            active_exists = active_path.exists()
            archive_exists = archive_path.exists()

        self.assertEqual(reconstructed["status"], "released")
        self.assertTrue(reconstructed["reconstructed"])
        self.assertFalse(active_exists)
        self.assertTrue(archive_exists)

    def test_reconcile_finishes_a_released_locator_after_sheet_rows_were_reclaimed(self) -> None:
        rows = ready_rows()[:1]
        store = MemoryFlowSheetStore(rows)
        expected_values = guards("PAGE-001")
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001"],
                lease_seconds=3600,
                expected_values=expected_values,
            )
            rows[0].values.update(
                {
                    "frontend status": "doing",
                    "frontend lease_token": "new-lease",
                    "frontend lease_until": "2099-01-01T00:00:00Z",
                }
            )
            active_path = queue._locator_path("book", "Tasks", "iole-flow-abc")
            archive_path = queue._released_locator_path(
                "book", "Tasks", "iole-flow-abc", "flow-lease-1"
            )
            real_replace = os.replace

            def interrupt_archive(source, target):
                if Path(source) == active_path and Path(target) == archive_path:
                    raise RuntimeError("interrupted after release write-ahead")
                return real_replace(source, target)

            with patch.object(flow_module.os, "replace", side_effect=interrupt_archive):
                with self.assertRaisesRegex(RuntimeError, "release write-ahead"):
                    queue.reconcile_flow_claim(
                        "book",
                        "Tasks",
                        mapping(),
                        flow_id="iole-flow-abc",
                        lease_token="flow-lease-1",
                        expected_values=expected_values,
                    )
            inspection = queue.inspect_active_flow_claims(
                "book", "Tasks", mapping()
            )
            reconstructed = queue.reconcile_flow_claim(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                lease_token="flow-lease-1",
                expected_values=expected_values,
            )

        self.assertEqual(inspection["status"], "active")
        self.assertEqual(inspection["claims"][0]["phase"], "released")
        self.assertEqual(inspection["claims"][0]["release_state"], "terminal")
        self.assertEqual(reconstructed["status"], "released")
        self.assertTrue(reconstructed["reconciled"])
        self.assertTrue(reconstructed["stale_locator"])

    def test_first_locator_write_is_atomic(self) -> None:
        store = MemoryFlowSheetStore(ready_rows()[:1])
        expected_values = guards("PAGE-001")
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            active_path = queue._locator_path("book", "Tasks", "iole-flow-abc")
            with patch.object(
                flow_module.os,
                "replace",
                side_effect=RuntimeError("interrupted atomic publish"),
            ):
                with self.assertRaisesRegex(RuntimeError, "atomic publish"):
                    queue.claim_flow(
                        "book",
                        "Tasks",
                        mapping(),
                        flow_id="iole-flow-abc",
                        row_ids=["PAGE-001"],
                        lease_seconds=3600,
                        expected_values=expected_values,
                    )
            active_exists = active_path.exists()

        self.assertFalse(active_exists)

    def test_release_keeps_locator_when_post_write_acknowledgement_drifts(self) -> None:
        store = DriftAfterUpdateFlowSheetStore(ready_rows())
        all_guards = guards("PAGE-001", "PAGE-002", "PAGE-003")
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001", "PAGE-002", "PAGE-003"],
                lease_seconds=3600,
                expected_values=all_guards,
            )
            store.drift_next_update = True

            with self.assertRaisesRegex(
                ValueError,
                "flow release acknowledgement drift",
            ):
                queue.release_flow_claim(
                    "book",
                    "Tasks",
                    mapping(),
                    flow_id="iole-flow-abc",
                    lease_token="flow-lease-1",
                    expected_values=all_guards,
                )
            locator_remains = queue._locator_path(
                "book",
                "Tasks",
                "iole-flow-abc",
            ).exists()

        self.assertTrue(locator_remains)

    def test_reconciles_terminal_review_member_for_explicit_restart(self) -> None:
        rows = ready_rows()[:1]
        rows[0].values["业务字段"] = "保留"
        rows[0].values["backend status"] = "doing"
        rows[0].values["backend lease_token"] = "backend-lease"
        store = MemoryFlowSheetStore(rows)
        expected_values = guards("PAGE-001")
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001"],
                lease_seconds=3600,
                expected_values=expected_values,
            )
            rows[0].values.update(
                {
                    "frontend status": "review",
                    "frontend last_error": "verification/failed",
                }
            )

            reconciled = queue.reconcile_flow_claim(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                lease_token="flow-lease-1",
                expected_values=expected_values,
            )
            active_exists = queue._locator_path(
                "book",
                "Tasks",
                "iole-flow-abc",
            ).exists()
            archive_exists = queue._released_locator_path(
                "book",
                "Tasks",
                "iole-flow-abc",
                "flow-lease-1",
            ).exists()
            reconstructed = queue.reconcile_flow_claim(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                lease_token="flow-lease-1",
                expected_values=expected_values,
            )

        self.assertEqual(reconciled["kind"], "icps.flow-release-result.v2")
        self.assertEqual(reconciled["status"], "released")
        self.assertTrue(reconciled["reconciled"])
        self.assertFalse(reconciled["stale_locator"])
        self.assertEqual(rows[0].values["frontend status"], "ready")
        self.assertEqual(rows[0].values["frontend lease_token"], "")
        self.assertEqual(rows[0].values["frontend lease_until"], "")
        self.assertEqual(rows[0].values["frontend last_error"], "")
        self.assertEqual(rows[0].values["frontend pr"], "")
        self.assertEqual(rows[0].values["业务字段"], "保留")
        self.assertEqual(rows[0].values["backend status"], "doing")
        self.assertEqual(rows[0].values["backend lease_token"], "backend-lease")
        self.assertFalse(active_exists)
        self.assertTrue(archive_exists)
        self.assertTrue(reconstructed["reconstructed"])
        self.assertTrue(reconstructed["reconciled"])
        self.assertFalse(reconstructed["stale_locator"])
        self.assertEqual(reconstructed["member_row_ids"], ["PAGE-001"])

    def test_reconcile_write_ahead_preserves_restart_mode_after_an_interruption(self) -> None:
        rows = ready_rows()[:1]
        store = MemoryFlowSheetStore(rows)
        expected_values = guards("PAGE-001")
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            queue.claim_flow(
                "book", "Tasks", mapping(), "iole-flow-abc", ["PAGE-001"], 3600,
                expected_values,
            )
            rows[0].values["frontend status"] = "review"
            real_replace_locator = queue._replace_locator
            statuses_when_intent_was_persisted = []

            def interrupt_before_second_locator(*args, **kwargs):
                locator = args[-1]
                if locator.get("release_mode") == "reconciled-restart":
                    statuses_when_intent_was_persisted.append(
                        rows[0].values["frontend status"]
                    )
                    real_replace_locator(*args, **kwargs)
                    raise RuntimeError("interrupted before reconcile locator")
                return real_replace_locator(*args, **kwargs)

            with patch.object(
                queue, "_replace_locator", side_effect=interrupt_before_second_locator
            ):
                with self.assertRaisesRegex(RuntimeError, "reconcile locator"):
                    queue.reconcile_flow_claim(
                        "book", "Tasks", mapping(), "iole-flow-abc", "flow-lease-1",
                        expected_values,
                    )

            reconstructed = queue.reconcile_flow_claim(
                "book", "Tasks", mapping(), "iole-flow-abc", "flow-lease-1",
                expected_values,
            )

        self.assertEqual(reconstructed["status"], "released")
        self.assertTrue(reconstructed["reconciled"])
        self.assertFalse(reconstructed["stale_locator"])
        self.assertEqual(statuses_when_intent_was_persisted, ["review"])

    def test_reconcile_rejects_the_same_lease_on_a_row_outside_the_locator(self) -> None:
        rows = ready_rows()[:2]
        store = MemoryFlowSheetStore(rows)
        expected_values = guards("PAGE-001")
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001"],
                lease_seconds=3600,
                expected_values=expected_values,
            )
            rows[0].values["frontend status"] = "review"
            rows[1].values.update(
                {
                    "frontend status": "doing",
                    "frontend lease_token": "flow-lease-1",
                    "frontend lease_until": rows[0].values["frontend lease_until"],
                }
            )

            with self.assertRaisesRegex(ValueError, "outside flow locator"):
                queue.reconcile_flow_claim(
                    "book",
                    "Tasks",
                    mapping(),
                    flow_id="iole-flow-abc",
                    lease_token="flow-lease-1",
                    expected_values=expected_values,
                )

        self.assertEqual(rows[0].values["frontend status"], "review")
        self.assertEqual(rows[1].values["frontend lease_token"], "flow-lease-1")

    def test_reconciles_orphaned_locator_without_mutating_drifted_sheet(self) -> None:
        rows = ready_rows()[:1]
        store = MemoryFlowSheetStore(rows)
        expected_values = guards("PAGE-001")
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001"],
                lease_seconds=3600,
                expected_values=expected_values,
            )
            rows[0].values.update(
                {
                    "编号": "PAGE-NEW",
                    "标题": "新任务",
                    "frontend status": "ready",
                    "frontend pr": "https://example.test/pr/2",
                    "frontend lease_token": "",
                    "frontend lease_until": "",
                    "frontend last_error": "",
                }
            )
            drifted_values = dict(rows[0].values)

            reconciled = queue.reconcile_flow_claim(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                lease_token="flow-lease-1",
                expected_values=expected_values,
            )
            active_exists = queue._locator_path(
                "book",
                "Tasks",
                "iole-flow-abc",
            ).exists()
            archive_exists = queue._released_locator_path(
                "book",
                "Tasks",
                "iole-flow-abc",
                "flow-lease-1",
            ).exists()

        self.assertEqual(reconciled["kind"], "icps.flow-release-result.v2")
        self.assertEqual(reconciled["status"], "released")
        self.assertTrue(reconciled["reconciled"])
        self.assertTrue(reconciled["stale_locator"])
        self.assertEqual(reconciled["rows"], [])
        self.assertEqual(rows[0].values, drifted_values)
        self.assertEqual(len(store.batch_updates), 1)
        self.assertFalse(active_exists)
        self.assertTrue(archive_exists)

    def test_reconstructs_orphaned_locator_reconciliation(self) -> None:
        rows = ready_rows()[:1]
        store = MemoryFlowSheetStore(rows)
        expected_values = guards("PAGE-001")
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001"],
                lease_seconds=3600,
                expected_values=expected_values,
            )
            rows[0].values.update(
                {
                    "编号": "PAGE-NEW",
                    "标题": "新任务",
                    "frontend status": "ready",
                    "frontend lease_token": "",
                    "frontend lease_until": "",
                }
            )
            queue.reconcile_flow_claim(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                lease_token="flow-lease-1",
                expected_values=expected_values,
            )

            reconstructed = queue.reconcile_flow_claim(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                lease_token="flow-lease-1",
                expected_values=expected_values,
            )

        self.assertEqual(reconstructed["status"], "released")
        self.assertTrue(reconstructed["reconstructed"])
        self.assertTrue(reconstructed["reconciled"])
        self.assertTrue(reconstructed["stale_locator"])
        self.assertEqual(reconstructed["rows"], [])
        self.assertEqual(len(store.batch_updates), 1)

    def test_claims_flow_members_by_unique_titles_without_a_number_column(self) -> None:
        rows = [
            SheetRow(
                number,
                {
                    "标题": title,
                    "frontend status": "ready",
                    "frontend pr": "",
                    "frontend lease_token": "",
                    "frontend lease_until": "",
                    "frontend last_error": "",
                },
            )
            for number, title in ((2, "申请首页"), (3, "职业信息页"))
        ]
        title_mapping = FlowQueueMapping(
            row_id="标题",
            status="frontend status",
            lease_token="frontend lease_token",
            lease_until="frontend lease_until",
            pr_url="frontend pr",
            last_error="frontend last_error",
            ready="ready",
            doing="doing",
            review="review",
            done="done",
        )
        expected_values = {
            "申请首页": {"frontend pr": ""},
            "职业信息页": {"frontend pr": ""},
        }
        store = MemoryFlowSheetStore(rows)
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-title",
            )
            inspected = queue.inspect_flow_rows(
                "book",
                "Tasks",
                title_mapping,
                ["申请首页", "职业信息页"],
            )
            claimed = queue.claim_flow(
                "book",
                "Tasks",
                title_mapping,
                flow_id="iole-flow-title",
                row_ids=["申请首页", "职业信息页"],
                lease_seconds=3600,
                expected_values=expected_values,
            )

        self.assertEqual(
            [row["标题"] for row in inspected["rows"]],
            ["申请首页", "职业信息页"],
        )
        self.assertEqual(claimed["status"], "claimed")
        self.assertEqual(claimed["lease_token"], "flow-lease-title")
        self.assertTrue(
            all(row.values["frontend status"] == "doing" for row in store.rows)
        )

    def test_claim_requires_nonempty_immutable_guards_for_every_member(self) -> None:
        store = MemoryFlowSheetStore(ready_rows())
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(store=store, lock_root=Path(lock_directory))
            with self.assertRaisesRegex(
                ValueError, "flow expected values do not cover every member"
            ):
                queue.claim_flow(
                    "book",
                    "Tasks",
                    mapping(),
                    flow_id="iole-flow-abc",
                    row_ids=["PAGE-001", "PAGE-002"],
                    lease_seconds=3600,
                    expected_values=guards("PAGE-001"),
                )

        self.assertEqual(store.batch_updates, [])

    def test_flow_guards_must_include_the_existing_pr_value(self) -> None:
        store = MemoryFlowSheetStore(ready_rows()[:1])
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(store=store, lock_root=Path(lock_directory))
            with self.assertRaisesRegex(ValueError, "existing PR value"):
                queue.claim_flow(
                    "book",
                    "Tasks",
                    mapping(),
                    flow_id="iole-flow-abc",
                    row_ids=["PAGE-001"],
                    lease_seconds=3600,
                    expected_values={"PAGE-001": {"标题": "申请首页"}},
                )

        self.assertEqual(store.batch_updates, [])

    def test_inspects_one_ready_root_without_claiming_or_mutating_it(self) -> None:
        store = MemoryFlowSheetStore(ready_rows())
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(store=store, lock_root=Path(lock_directory))
            result = queue.inspect_ready_root("book", "Tasks", mapping())

        self.assertEqual(result["status"], "ready-root")
        self.assertEqual(result["row"]["编号"], "PAGE-001")
        self.assertEqual(result["row_number"], 2)
        self.assertEqual(store.batch_updates, [])
        self.assertEqual(store.rows[0].values["frontend status"], "ready")

    def test_inspects_the_complete_title_catalog_without_reading_row_contents(self) -> None:
        title_mapping = FlowQueueMapping(
            row_id="标题",
            status="frontend status",
            lease_token="frontend lease_token",
            lease_until="frontend lease_until",
            pr_url="frontend pr",
            last_error="frontend last_error",
            ready="ready",
            doing="doing",
            review="review",
            done="done",
        )
        store = MemoryFlowSheetStore(ready_rows())
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(store=store, lock_root=Path(lock_directory))
            result = queue.inspect_title_catalog("book", "Tasks", title_mapping)

        self.assertEqual(result["kind"], "icps.flow-title-catalog.v1")
        self.assertEqual(result["spreadsheet_id"], "book")
        self.assertEqual(result["sheet_name"], "Tasks")
        self.assertEqual(result["row_id_column"], "标题")
        self.assertEqual(
            result["titles"], ["申请首页", "职业信息页", "申请结果页"]
        )
        self.assertEqual(len(result["catalog_digest"]), 64)
        self.assertEqual(store.batch_updates, [])

    def test_inspects_only_declared_child_identities_without_claiming_them(self) -> None:
        rows = ready_rows()
        rows.insert(
            1,
            SheetRow(
                5,
                {
                    "编号": "UNRELATED",
                    "frontend status": "done",
                    "frontend pr": "",
                    "frontend lease_token": "",
                    "frontend lease_until": "",
                    "frontend last_error": "",
                },
            ),
        )
        store = MemoryFlowSheetStore(rows)
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(store=store, lock_root=Path(lock_directory))
            result = queue.inspect_flow_rows(
                "book",
                "Tasks",
                mapping(),
                row_ids=["PAGE-002", "PAGE-003"],
            )

        self.assertEqual(result["status"], "inspected")
        self.assertEqual(
            [row["编号"] for row in result["rows"]], ["PAGE-002", "PAGE-003"]
        )
        self.assertEqual(store.batch_updates, [])

    def test_claims_every_flow_member_with_one_shared_lease_and_one_batch(self) -> None:
        store = MemoryFlowSheetStore(ready_rows())
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                clock=lambda: datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc),
                token_factory=lambda: "flow-lease-1",
            )
            result = queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001", "PAGE-002", "PAGE-003"],
                lease_seconds=3600,
                expected_values=guards("PAGE-001", "PAGE-002", "PAGE-003"),
            )

        self.assertEqual(result["status"], "claimed")
        self.assertEqual(result["lease_token"], "flow-lease-1")
        self.assertEqual(len(store.batch_updates), 1)
        self.assertEqual(set(store.batch_updates[0]), {2, 3, 4})
        for row in store.rows:
            self.assertEqual(row.values["frontend status"], "doing")
            self.assertEqual(row.values["frontend lease_token"], "flow-lease-1")
            self.assertEqual(
                row.values["frontend lease_until"], "2026-08-13T09:00:00Z"
            )

    def test_claim_mutates_nothing_when_one_member_is_not_ready(self) -> None:
        rows = ready_rows()
        rows[1].values["frontend status"] = "doing"
        rows[1].values["frontend lease_token"] = "other-worker"
        store = MemoryFlowSheetStore(rows)
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            with self.assertRaisesRegex(ValueError, "flow member is not ready"):
                queue.claim_flow(
                    "book",
                    "Tasks",
                    mapping(),
                    flow_id="iole-flow-abc",
                    row_ids=["PAGE-001", "PAGE-002", "PAGE-003"],
                    lease_seconds=3600,
                    expected_values=guards("PAGE-001", "PAGE-002", "PAGE-003"),
                )

        self.assertEqual(store.batch_updates, [])
        self.assertEqual(store.rows[0].values["frontend status"], "ready")
        self.assertEqual(store.rows[2].values["frontend status"], "ready")
        self.assertEqual(store.rows[1].values["frontend lease_token"], "other-worker")

    def test_expands_an_active_flow_before_the_new_page_is_edited(self) -> None:
        store = MemoryFlowSheetStore(ready_rows())
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001", "PAGE-002"],
                lease_seconds=3600,
                expected_values=guards("PAGE-001", "PAGE-002"),
            )
            result = queue.expand_flow_claim(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                lease_token="flow-lease-1",
                row_ids=["PAGE-003"],
                expected_values=guards("PAGE-003"),
            )

        self.assertEqual(result["status"], "expanded")
        self.assertEqual(
            result["member_row_ids"], ["PAGE-001", "PAGE-002", "PAGE-003"]
        )
        self.assertEqual(len(store.batch_updates), 2)
        self.assertEqual(set(store.batch_updates[1]), {4})
        self.assertEqual(store.rows[2].values["frontend status"], "doing")
        self.assertEqual(
            store.rows[2].values["frontend lease_token"], "flow-lease-1"
        )

    def test_reconstructs_an_expansion_after_the_batch_response_is_lost(self) -> None:
        store = LostResponseFlowSheetStore(ready_rows())
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001", "PAGE-002"],
                lease_seconds=3600,
                expected_values=guards("PAGE-001", "PAGE-002"),
            )
            store.lose_next_update_response = True
            with self.assertRaisesRegex(RuntimeError, "simulated lost response"):
                queue.expand_flow_claim(
                    "book",
                    "Tasks",
                    mapping(),
                    flow_id="iole-flow-abc",
                    lease_token="flow-lease-1",
                    row_ids=["PAGE-003"],
                    expected_values=guards("PAGE-003"),
                )
            reconstructed = queue.expand_flow_claim(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                lease_token="flow-lease-1",
                row_ids=["PAGE-003"],
                expected_values=guards("PAGE-003"),
            )

        self.assertTrue(reconstructed["reconstructed"])
        self.assertEqual(
            reconstructed["member_row_ids"],
            ["PAGE-001", "PAGE-002", "PAGE-003"],
        )
        self.assertEqual(len(store.batch_updates), 2)

    def test_completes_all_members_to_review_with_one_shared_pr(self) -> None:
        store = MemoryFlowSheetStore(ready_rows())
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001", "PAGE-002", "PAGE-003"],
                lease_seconds=3600,
                expected_values=guards("PAGE-001", "PAGE-002", "PAGE-003"),
            )
            result = queue.complete_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                lease_token="flow-lease-1",
                pr_url="https://git.example/team/app/pull/9",
                expected_values=guards("PAGE-001", "PAGE-002", "PAGE-003"),
            )
            inspection = queue.inspect_active_flow_claims(
                "book", "Tasks", mapping()
            )
            active_exists = queue._locator_path(
                "book", "Tasks", "iole-flow-abc"
            ).exists()

        self.assertEqual(result["status"], "review")
        self.assertFalse(result["reconstructed"])
        self.assertEqual(len(store.batch_updates), 2)
        self.assertEqual(set(store.batch_updates[1]), {2, 3, 4})
        self.assertEqual(inspection["status"], "none")
        self.assertFalse(active_exists)
        for row in store.rows:
            self.assertEqual(row.values["frontend status"], "review")
            self.assertEqual(
                row.values["frontend pr"], "https://git.example/team/app/pull/9"
            )
            self.assertEqual(row.values["frontend lease_token"], "")
            self.assertEqual(row.values["frontend lease_until"], "")

    def test_completion_without_mr_preserves_pr_and_moves_all_members_to_review(self) -> None:
        store = MemoryFlowSheetStore(ready_rows())
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001", "PAGE-002", "PAGE-003"],
                lease_seconds=3600,
                expected_values=guards("PAGE-001", "PAGE-002", "PAGE-003"),
            )
            result = queue.complete_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                lease_token="flow-lease-1",
                pr_url=None,
                expected_values=guards("PAGE-001", "PAGE-002", "PAGE-003"),
            )

        self.assertEqual(result["status"], "review")
        self.assertIsNone(result["pr_url"])
        for row in store.rows:
            self.assertEqual(row.values["frontend status"], "review")
            self.assertEqual(row.values["frontend pr"], "")

    def test_completion_mutates_nothing_when_one_member_drifted(self) -> None:
        store = MemoryFlowSheetStore(ready_rows())
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001", "PAGE-002", "PAGE-003"],
                lease_seconds=3600,
                expected_values=guards("PAGE-001", "PAGE-002", "PAGE-003"),
            )
            store.rows[1].values["标题"] = "外部修改"
            with self.assertRaisesRegex(ValueError, "flow member input drift"):
                queue.complete_flow(
                    "book",
                    "Tasks",
                    mapping(),
                    flow_id="iole-flow-abc",
                    lease_token="flow-lease-1",
                    pr_url="https://git.example/team/app/pull/9",
                    expected_values=guards("PAGE-001", "PAGE-002", "PAGE-003"),
                )

        self.assertEqual(len(store.batch_updates), 1)
        for row in store.rows:
            self.assertEqual(row.values["frontend status"], "doing")
            self.assertEqual(row.values["frontend pr"], "")

    def test_completion_cannot_replace_the_guards_bound_at_claim_time(self) -> None:
        store = MemoryFlowSheetStore(ready_rows())
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001", "PAGE-002", "PAGE-003"],
                lease_seconds=3600,
                expected_values=guards("PAGE-001", "PAGE-002", "PAGE-003"),
            )
            store.rows[1].values["标题"] = "外部修改"
            adaptive_guards = guards("PAGE-001", "PAGE-002", "PAGE-003")
            adaptive_guards["PAGE-002"]["标题"] = "外部修改"
            with self.assertRaisesRegex(
                ValueError, "flow expected values do not match claim locator"
            ):
                queue.complete_flow(
                    "book",
                    "Tasks",
                    mapping(),
                    flow_id="iole-flow-abc",
                    lease_token="flow-lease-1",
                    pr_url="https://git.example/team/app/pull/9",
                    expected_values=adaptive_guards,
                )

        self.assertEqual(len(store.batch_updates), 1)
        self.assertTrue(
            all(row.values["frontend status"] == "doing" for row in store.rows)
        )

    def test_reconstructs_a_lost_terminal_response_for_the_whole_flow(self) -> None:
        store = MemoryFlowSheetStore(ready_rows())
        all_guards = guards("PAGE-001", "PAGE-002", "PAGE-003")
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001", "PAGE-002", "PAGE-003"],
                lease_seconds=3600,
                expected_values=all_guards,
            )
            queue.complete_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                lease_token="flow-lease-1",
                pr_url="https://git.example/team/app/pull/9",
                expected_values=all_guards,
            )
            reconstructed = queue.complete_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                lease_token="flow-lease-1",
                pr_url="https://git.example/team/app/pull/9",
                expected_values=all_guards,
            )

        self.assertTrue(reconstructed["reconstructed"])
        self.assertEqual(reconstructed["status"], "review")
        self.assertEqual(len(store.batch_updates), 2)

    def test_completion_recovers_when_interrupted_after_write_ahead_before_sheet_update(self) -> None:
        store = MemoryFlowSheetStore(ready_rows())
        all_guards = guards("PAGE-001", "PAGE-002", "PAGE-003")
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            queue.claim_flow(
                "book", "Tasks", mapping(), "iole-flow-abc",
                ["PAGE-001", "PAGE-002", "PAGE-003"], 3600, all_guards,
            )
            with patch.object(
                store, "update_rows", side_effect=RuntimeError("interrupted")
            ):
                with self.assertRaisesRegex(RuntimeError, "interrupted"):
                    queue.complete_flow(
                        "book", "Tasks", mapping(), "iole-flow-abc",
                        "flow-lease-1", None, all_guards,
                    )
            inspection = queue.inspect_active_flow_claims(
                "book", "Tasks", mapping()
            )
            recovered = queue.complete_flow(
                "book", "Tasks", mapping(), "iole-flow-abc",
                "flow-lease-1", None, all_guards,
            )

        self.assertEqual(inspection["status"], "active")
        self.assertEqual(inspection["claims"][0]["completion_state"], "prepared")
        self.assertTrue(recovered["reconstructed"])
        self.assertEqual(recovered["status"], "review")

    def test_completion_recovers_when_interrupted_after_sheet_update_before_archive(self) -> None:
        store = MemoryFlowSheetStore(ready_rows())
        all_guards = guards("PAGE-001", "PAGE-002", "PAGE-003")
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            queue.claim_flow(
                "book", "Tasks", mapping(), "iole-flow-abc",
                ["PAGE-001", "PAGE-002", "PAGE-003"], 3600, all_guards,
            )
            real_replace = os.replace
            calls = 0

            def interrupt_archive(source, target):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise RuntimeError("interrupted")
                return real_replace(source, target)

            with patch.object(flow_module.os, "replace", side_effect=interrupt_archive):
                with self.assertRaisesRegex(RuntimeError, "interrupted"):
                    queue.complete_flow(
                        "book", "Tasks", mapping(), "iole-flow-abc",
                        "flow-lease-1", None, all_guards,
                    )
            inspection = queue.inspect_active_flow_claims(
                "book", "Tasks", mapping()
            )
            recovered = queue.complete_flow(
                "book", "Tasks", mapping(), "iole-flow-abc",
                "flow-lease-1", None, all_guards,
            )

        self.assertEqual(inspection["status"], "active")
        self.assertEqual(inspection["claims"][0]["completion_state"], "terminal")
        self.assertTrue(recovered["reconstructed"])
        self.assertEqual(recovered["status"], "review")

    def test_records_one_controlled_error_on_every_active_member(self) -> None:
        store = MemoryFlowSheetStore(ready_rows())
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001", "PAGE-002", "PAGE-003"],
                lease_seconds=3600,
                expected_values=guards("PAGE-001", "PAGE-002", "PAGE-003"),
            )
            result = queue.record_flow_error(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                lease_token="flow-lease-1",
                error_code="worker/node-failed",
                expected_values=guards("PAGE-001", "PAGE-002", "PAGE-003"),
            )

        self.assertEqual(result["status"], "error-recorded")
        self.assertEqual(len(store.batch_updates), 2)
        for row in store.rows:
            self.assertEqual(row.values["frontend status"], "doing")
            self.assertEqual(
                row.values["frontend last_error"], "worker/node-failed"
            )

    def test_reconstructs_a_lost_claim_response_from_the_flow_locator(self) -> None:
        store = MemoryFlowSheetStore(ready_rows())
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001", "PAGE-002", "PAGE-003"],
                lease_seconds=3600,
                expected_values=guards("PAGE-001", "PAGE-002", "PAGE-003"),
            )
            reconstructed = queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001", "PAGE-002", "PAGE-003"],
                lease_seconds=3600,
                expected_values=guards("PAGE-001", "PAGE-002", "PAGE-003"),
            )

        self.assertTrue(reconstructed["reconstructed"])
        self.assertEqual(reconstructed["lease_token"], "flow-lease-1")
        self.assertEqual(len(store.batch_updates), 1)

    def test_retries_claim_when_the_first_batch_failed_before_mutation(self) -> None:
        store = FailBeforeUpdateFlowSheetStore(ready_rows())
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            store.fail_next_update = True
            with self.assertRaisesRegex(RuntimeError, "simulated pre-write failure"):
                queue.claim_flow(
                    "book",
                    "Tasks",
                    mapping(),
                    flow_id="iole-flow-abc",
                    row_ids=["PAGE-001", "PAGE-002", "PAGE-003"],
                    lease_seconds=3600,
                    expected_values=guards("PAGE-001", "PAGE-002", "PAGE-003"),
                )
            retried = queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001", "PAGE-002", "PAGE-003"],
                lease_seconds=3600,
                expected_values=guards("PAGE-001", "PAGE-002", "PAGE-003"),
            )

        self.assertEqual(retried["status"], "claimed")
        self.assertFalse(retried["reconstructed"])
        self.assertEqual(len(store.batch_updates), 1)

    def test_retries_expansion_when_the_first_batch_failed_before_mutation(self) -> None:
        store = FailBeforeUpdateFlowSheetStore(ready_rows())
        with tempfile.TemporaryDirectory() as lock_directory:
            queue = AtomicSheetFlowQueue(
                store=store,
                lock_root=Path(lock_directory),
                token_factory=lambda: "flow-lease-1",
            )
            queue.claim_flow(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                row_ids=["PAGE-001", "PAGE-002"],
                lease_seconds=3600,
                expected_values=guards("PAGE-001", "PAGE-002"),
            )
            store.fail_next_update = True
            with self.assertRaisesRegex(RuntimeError, "simulated pre-write failure"):
                queue.expand_flow_claim(
                    "book",
                    "Tasks",
                    mapping(),
                    flow_id="iole-flow-abc",
                    lease_token="flow-lease-1",
                    row_ids=["PAGE-003"],
                    expected_values=guards("PAGE-003"),
                )
            retried = queue.expand_flow_claim(
                "book",
                "Tasks",
                mapping(),
                flow_id="iole-flow-abc",
                lease_token="flow-lease-1",
                row_ids=["PAGE-003"],
                expected_values=guards("PAGE-003"),
            )

        self.assertEqual(retried["status"], "expanded")
        self.assertFalse(retried["reconstructed"])
        self.assertEqual(len(store.batch_updates), 2)


if __name__ == "__main__":
    unittest.main()
