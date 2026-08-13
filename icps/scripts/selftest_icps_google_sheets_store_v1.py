#!/usr/bin/env python3
from __future__ import annotations

import unittest

from icps_google_sheets_mcp import GoogleSheetStore


class FakeRequest:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response

    def execute(self) -> dict[str, object]:
        return self.response


class FakeValuesResource:
    def __init__(self, responses: dict[str, dict[str, object]]) -> None:
        self.responses = responses
        self.ranges: list[str] = []
        self.batch_bodies: list[dict[str, object]] = []

    def get(self, *, spreadsheetId: str, range: str) -> FakeRequest:
        self.ranges.append(range)
        return FakeRequest(self.responses[range])

    def batchUpdate(
        self, *, spreadsheetId: str, body: dict[str, object]
    ) -> FakeRequest:
        self.batch_bodies.append(body)
        return FakeRequest({"updatedCells": len(body.get("data", []))})


class FakeSpreadsheetsResource:
    def __init__(self, values_resource: FakeValuesResource) -> None:
        self.values_resource = values_resource

    def values(self) -> FakeValuesResource:
        return self.values_resource


class FakeSheetsService:
    def __init__(self, values_resource: FakeValuesResource) -> None:
        self.spreadsheets_resource = FakeSpreadsheetsResource(values_resource)

    def spreadsheets(self) -> FakeSpreadsheetsResource:
        return self.spreadsheets_resource


class GoogleSheetStoreTests(unittest.TestCase):
    def test_ready_lookup_reads_only_status_column_then_selected_row(self) -> None:
        responses = {
            "'Tasks'!1:1": {"values": [["编号", "状态", "标题"]]},
            "'Tasks'!B2:B": {"values": [["done"], ["ready"]]},
            "'Tasks'!3:3": {"values": [["22", "ready", "权限声明"]]},
        }
        values_resource = FakeValuesResource(responses)
        store = GoogleSheetStore(FakeSheetsService(values_resource))

        row_number = store.find_first_row_number(
            "book",
            "Tasks",
            "状态",
            "ready",
        )
        row = store.read_row("book", "Tasks", row_number or 0)

        self.assertEqual(row_number, 3)
        self.assertEqual(row.values["编号"], "22")
        self.assertEqual(row.values["标题"], "权限声明")
        self.assertEqual(
            values_resource.ranges,
            ["'Tasks'!1:1", "'Tasks'!B2:B", "'Tasks'!1:1", "'Tasks'!3:3"],
        )

    def test_flow_lookup_reads_only_the_title_column_for_declared_titles(self) -> None:
        responses = {
            "'Tasks'!1:1": {"values": [["状态", "标题"]]},
            "'Tasks'!B2:B": {
                "values": [["申请首页"], ["其他页面"], ["申请结果页"]]
            },
        }
        values_resource = FakeValuesResource(responses)
        store = GoogleSheetStore(FakeSheetsService(values_resource))

        result = store.find_row_numbers_by_ids(
            "book",
            "Tasks",
            "标题",
            ["申请首页", "申请结果页"],
        )

        self.assertEqual(result, {"申请首页": 2, "申请结果页": 4})
        self.assertEqual(values_resource.ranges, ["'Tasks'!1:1", "'Tasks'!B2:B"])

    def test_flow_lookup_rejects_duplicate_declared_titles(self) -> None:
        responses = {
            "'Tasks'!1:1": {"values": [["状态", "标题"]]},
            "'Tasks'!B2:B": {"values": [["申请首页"], ["申请首页"]]},
        }
        store = GoogleSheetStore(FakeSheetsService(FakeValuesResource(responses)))

        with self.assertRaisesRegex(
            ValueError, "duplicate sheet row identity: 申请首页"
        ):
            store.find_row_numbers_by_ids(
                "book",
                "Tasks",
                "标题",
                ["申请首页"],
            )

    def test_flow_update_writes_every_member_in_one_values_batch(self) -> None:
        responses = {
            "'Tasks'!1:1": {
                "values": [["编号", "frontend status", "frontend lease_token"]]
            },
            "'Tasks'!2:2": {"values": [["PAGE-001", "doing", "flow-lease"]]},
            "'Tasks'!4:4": {"values": [["PAGE-003", "doing", "flow-lease"]]},
        }
        values_resource = FakeValuesResource(responses)
        store = GoogleSheetStore(FakeSheetsService(values_resource))

        updated = store.update_rows(
            "book",
            "Tasks",
            {
                2: {
                    "frontend status": "doing",
                    "frontend lease_token": "flow-lease",
                },
                4: {
                    "frontend status": "doing",
                    "frontend lease_token": "flow-lease",
                },
            },
        )

        self.assertEqual([row.row_number for row in updated], [2, 4])
        self.assertEqual(len(values_resource.batch_bodies), 1)
        data = values_resource.batch_bodies[0]["data"]
        self.assertEqual(
            {item["range"] for item in data},
            {"'Tasks'!B2", "'Tasks'!C2", "'Tasks'!B4", "'Tasks'!C4"},
        )


if __name__ == "__main__":
    unittest.main()
