#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

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

        self.assertEqual(result["status"], "review")
        self.assertFalse(result["reconstructed"])
        self.assertEqual(len(store.batch_updates), 2)
        self.assertEqual(set(store.batch_updates[1]), {2, 3, 4})
        for row in store.rows:
            self.assertEqual(row.values["frontend status"], "review")
            self.assertEqual(
                row.values["frontend pr"], "https://git.example/team/app/pull/9"
            )
            self.assertEqual(row.values["frontend lease_token"], "")
            self.assertEqual(row.values["frontend lease_until"], "")

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
