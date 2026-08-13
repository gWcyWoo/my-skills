#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "google-api-python-client>=2.0,<3",
#   "google-auth>=2.0,<3",
#   "mcp>=1.0,<2",
# ]
# ///
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build
from mcp.server.fastmcp import FastMCP

from icps_atomic_sheets_v1 import AtomicSheetQueue, QueueMapping, SheetRow
from icps_atomic_sheets_v2 import AtomicSheetFlowQueue, FlowQueueMapping


SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
MCP_NAME = "icps-google-sheets"
mcp = FastMCP(MCP_NAME)


def quote_sheet_name(sheet_name: str) -> str:
    return "'" + sheet_name.replace("'", "''") + "'"


def column_letter(column_number: int) -> str:
    if column_number < 1:
        raise ValueError("column number must be positive")
    letters = ""
    while column_number:
        column_number, remainder = divmod(column_number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


class GoogleSheetStore:
    def __init__(self, service: Any) -> None:
        self.service = service

    def _values(self, spreadsheet_id: str, cell_range: str) -> list[list[Any]]:
        response = (
            self.service.spreadsheets()
            .values()
            .get(
                spreadsheetId=spreadsheet_id,
                range=cell_range,
            )
            .execute()
        )
        return response.get("values", [])

    def _headers(self, spreadsheet_id: str, sheet_name: str) -> list[str]:
        values = self._values(
            spreadsheet_id,
            f"{quote_sheet_name(sheet_name)}!1:1",
        )
        if not values:
            raise ValueError("sheet has no header row")
        headers = [str(value).strip() for value in values[0]]
        if not all(headers) or len(headers) != len(set(headers)):
            raise ValueError("sheet headers must be non-empty and unique")
        return headers

    def find_first_row_number(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        column: str,
        value: str,
    ) -> int | None:
        headers = self._headers(spreadsheet_id, sheet_name)
        try:
            column_number = headers.index(column) + 1
        except ValueError as exc:
            raise ValueError(f"missing sheet columns: {column}") from exc
        column_name = column_letter(column_number)
        values = self._values(
            spreadsheet_id,
            f"{quote_sheet_name(sheet_name)}!{column_name}2:{column_name}",
        )
        for row_number, source_values in enumerate(values, start=2):
            cell_value = "" if not source_values else str(source_values[0])
            if cell_value == value:
                return row_number
        return None

    def find_row_numbers_by_ids(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        column: str,
        row_ids: list[str],
    ) -> dict[str, int]:
        if not row_ids or len(row_ids) != len(set(row_ids)):
            raise ValueError("flow row identities are invalid")
        headers = self._headers(spreadsheet_id, sheet_name)
        try:
            column_number = headers.index(column) + 1
        except ValueError as exc:
            raise ValueError(f"missing sheet columns: {column}") from exc
        column_name = column_letter(column_number)
        values = self._values(
            spreadsheet_id,
            f"{quote_sheet_name(sheet_name)}!{column_name}2:{column_name}",
        )
        requested = set(row_ids)
        matches: dict[str, int] = {}
        for row_number, source_values in enumerate(values, start=2):
            cell_value = "" if not source_values else str(source_values[0]).strip()
            if cell_value not in requested:
                continue
            if cell_value in matches:
                raise ValueError(f"duplicate sheet row identity: {cell_value}")
            matches[cell_value] = row_number
        return matches

    def read_row(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        row_number: int,
    ) -> SheetRow:
        if row_number < 2:
            raise ValueError("row number must identify a data row")
        headers = self._headers(spreadsheet_id, sheet_name)
        values = self._values(
            spreadsheet_id,
            f"{quote_sheet_name(sheet_name)}!{row_number}:{row_number}",
        )
        source_values = [] if not values else values[0]
        padded = [*source_values, *([""] * (len(headers) - len(source_values)))]
        return SheetRow(
            row_number=row_number,
            values={header: str(padded[index]) for index, header in enumerate(headers)},
        )

    def read_rows(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        row_numbers: list[int],
    ) -> list[SheetRow]:
        if not row_numbers or len(row_numbers) != len(set(row_numbers)):
            raise ValueError("flow row numbers are invalid")
        return [
            self.read_row(spreadsheet_id, sheet_name, row_number)
            for row_number in row_numbers
        ]

    def update_row(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        row_number: int,
        updates: dict[str, str],
    ) -> SheetRow:
        headers = self._headers(spreadsheet_id, sheet_name)
        header_positions = {header: index + 1 for index, header in enumerate(headers)}
        missing = sorted(set(updates) - set(header_positions))
        if missing:
            raise ValueError("missing sheet columns: " + ", ".join(missing))

        quoted_sheet = quote_sheet_name(sheet_name)
        data = [
            {
                "range": (
                    f"{quoted_sheet}!{column_letter(header_positions[column])}{row_number}"
                ),
                "values": [[value]],
            }
            for column, value in updates.items()
        ]
        (
            self.service.spreadsheets()
            .values()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"valueInputOption": "RAW", "data": data},
            )
            .execute()
        )

        updated = self.read_row(spreadsheet_id, sheet_name, row_number)
        if any(updated.values.get(key) != value for key, value in updates.items()):
            raise ValueError("sheet write acknowledgement mismatch")
        return updated

    def update_rows(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        updates: dict[int, dict[str, str]],
    ) -> list[SheetRow]:
        if (
            not isinstance(updates, dict)
            or not updates
            or any(type(row_number) is not int or row_number < 2 for row_number in updates)
            or any(not isinstance(values, dict) or not values for values in updates.values())
        ):
            raise ValueError("flow row updates are invalid")
        headers = self._headers(spreadsheet_id, sheet_name)
        header_positions = {header: index + 1 for index, header in enumerate(headers)}
        requested_columns = {
            column for row_updates in updates.values() for column in row_updates
        }
        missing = sorted(requested_columns - set(header_positions))
        if missing:
            raise ValueError("missing sheet columns: " + ", ".join(missing))
        quoted_sheet = quote_sheet_name(sheet_name)
        data = [
            {
                "range": (
                    f"{quoted_sheet}!{column_letter(header_positions[column])}{row_number}"
                ),
                "values": [[value]],
            }
            for row_number, row_updates in updates.items()
            for column, value in row_updates.items()
        ]
        (
            self.service.spreadsheets()
            .values()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"valueInputOption": "RAW", "data": data},
            )
            .execute()
        )
        updated_rows = self.read_rows(
            spreadsheet_id,
            sheet_name,
            list(updates),
        )
        for row in updated_rows:
            if any(
                row.values.get(column) != expected
                for column, expected in updates[row.row_number].items()
            ):
                raise ValueError("sheet write acknowledgement mismatch")
        return updated_rows


def build_store_and_lock() -> tuple[GoogleSheetStore, Path]:
    credential_path = os.environ.get("SERVICE_ACCOUNT_PATH")
    if not credential_path:
        raise ValueError("SERVICE_ACCOUNT_PATH is required")
    credentials = service_account.Credentials.from_service_account_file(
        credential_path,
        scopes=SHEETS_SCOPES,
    )
    sheets_service = build(
        "sheets",
        "v4",
        credentials=credentials,
        cache_discovery=False,
    )
    default_lock_root = Path.home() / ".local" / "state" / "icps" / "locks"
    lock_root = Path(os.environ.get("ICPS_LOCK_DIR", str(default_lock_root)))
    return GoogleSheetStore(sheets_service), lock_root


def build_queue() -> AtomicSheetQueue:
    store, lock_root = build_store_and_lock()
    return AtomicSheetQueue(store, lock_root)


def build_flow_queue() -> AtomicSheetFlowQueue:
    store, lock_root = build_store_and_lock()
    return AtomicSheetFlowQueue(store, lock_root)


def mapping_from_arguments(
    row_id_column: str,
    status_column: str,
    lease_token_column: str,
    lease_until_column: str,
    pr_url_column: str,
    ready_value: str,
    doing_value: str,
    done_value: str,
    last_error_column: str | None = None,
) -> QueueMapping:
    return QueueMapping(
        row_id=row_id_column,
        status=status_column,
        lease_token=lease_token_column,
        lease_until=lease_until_column,
        pr_url=pr_url_column,
        ready=ready_value,
        doing=doing_value,
        done=done_value,
        last_error=last_error_column,
    )


def flow_mapping_from_arguments(
    row_id_column: str,
    status_column: str,
    lease_token_column: str,
    lease_until_column: str,
    pr_url_column: str,
    last_error_column: str,
    ready_value: str,
    doing_value: str,
    review_value: str,
    done_value: str,
) -> FlowQueueMapping:
    return FlowQueueMapping(
        row_id=row_id_column,
        status=status_column,
        lease_token=lease_token_column,
        lease_until=lease_until_column,
        pr_url=pr_url_column,
        last_error=last_error_column,
        ready=ready_value,
        doing=doing_value,
        review=review_value,
        done=done_value,
    )


@mcp.tool()
def claim_ready_row(
    spreadsheet_id: str,
    sheet_name: str,
    row_id_column: str,
    status_column: str,
    lease_token_column: str,
    lease_until_column: str,
    pr_url_column: str,
    ready_value: str = "ready",
    doing_value: str = "doing",
    done_value: str = "done",
    lease_seconds: int = 7200,
    last_error_column: str | None = None,
) -> dict[str, object]:
    """Claim the first ready row under a host-wide lock and return its updated values."""
    mapping = mapping_from_arguments(
        row_id_column,
        status_column,
        lease_token_column,
        lease_until_column,
        pr_url_column,
        ready_value,
        doing_value,
        done_value,
        last_error_column,
    )
    return build_queue().claim(
        spreadsheet_id,
        sheet_name,
        mapping,
        lease_seconds=lease_seconds,
    )


@mcp.tool()
def complete_claimed_row(
    spreadsheet_id: str,
    sheet_name: str,
    row_id_column: str,
    status_column: str,
    lease_token_column: str,
    lease_until_column: str,
    pr_url_column: str,
    row_id: str,
    lease_token: str,
    pr_url: str,
    ready_value: str = "ready",
    doing_value: str = "doing",
    done_value: str = "done",
    expected_values: dict[str, object] | None = None,
    last_error_column: str | None = None,
) -> dict[str, object]:
    """Write PR/status only when lease and optional immutable row values still match."""
    mapping = mapping_from_arguments(
        row_id_column,
        status_column,
        lease_token_column,
        lease_until_column,
        pr_url_column,
        ready_value,
        doing_value,
        done_value,
        last_error_column,
    )
    return build_queue().complete(
        spreadsheet_id,
        sheet_name,
        mapping,
        row_id=row_id,
        lease_token=lease_token,
        pr_url=pr_url,
        expected_values=expected_values,
    )


@mcp.tool()
def record_claim_error(
    spreadsheet_id: str,
    sheet_name: str,
    row_id_column: str,
    status_column: str,
    lease_token_column: str,
    lease_until_column: str,
    pr_url_column: str,
    last_error_column: str,
    row_id: str,
    lease_token: str,
    error_code: str,
    ready_value: str = "ready",
    doing_value: str = "doing",
    done_value: str = "done",
    expected_values: dict[str, object] | None = None,
) -> dict[str, object]:
    """Record one controlled error without releasing or changing the active claim."""
    mapping = mapping_from_arguments(
        row_id_column,
        status_column,
        lease_token_column,
        lease_until_column,
        pr_url_column,
        ready_value,
        doing_value,
        done_value,
        last_error_column,
    )
    return build_queue().record_error(
        spreadsheet_id,
        sheet_name,
        mapping,
        row_id=row_id,
        lease_token=lease_token,
        error_code=error_code,
        expected_values=expected_values,
    )


@mcp.tool()
def inspect_ready_flow_root(
    spreadsheet_id: str,
    sheet_name: str,
    row_id_column: str,
    status_column: str,
    lease_token_column: str,
    lease_until_column: str,
    pr_url_column: str,
    last_error_column: str,
    ready_value: str = "ready",
    doing_value: str = "doing",
    review_value: str = "review",
    done_value: str = "done",
) -> dict[str, object]:
    """Read the first ready flow root without claiming or mutating it."""
    mapping = flow_mapping_from_arguments(
        row_id_column,
        status_column,
        lease_token_column,
        lease_until_column,
        pr_url_column,
        last_error_column,
        ready_value,
        doing_value,
        review_value,
        done_value,
    )
    return build_flow_queue().inspect_ready_root(spreadsheet_id, sheet_name, mapping)


@mcp.tool()
def inspect_flow_rows(
    spreadsheet_id: str,
    sheet_name: str,
    row_id_column: str,
    status_column: str,
    lease_token_column: str,
    lease_until_column: str,
    pr_url_column: str,
    last_error_column: str,
    row_ids: list[str],
    ready_value: str = "ready",
    doing_value: str = "doing",
    review_value: str = "review",
    done_value: str = "done",
) -> dict[str, object]:
    """Read only rows whose stable identities were declared by the flow planner."""
    mapping = flow_mapping_from_arguments(
        row_id_column,
        status_column,
        lease_token_column,
        lease_until_column,
        pr_url_column,
        last_error_column,
        ready_value,
        doing_value,
        review_value,
        done_value,
    )
    return build_flow_queue().inspect_flow_rows(
        spreadsheet_id,
        sheet_name,
        mapping,
        row_ids,
    )


@mcp.tool()
def claim_flow_rows(
    spreadsheet_id: str,
    sheet_name: str,
    row_id_column: str,
    status_column: str,
    lease_token_column: str,
    lease_until_column: str,
    pr_url_column: str,
    last_error_column: str,
    flow_id: str,
    row_ids: list[str],
    expected_values: dict[str, dict[str, object]],
    ready_value: str = "ready",
    doing_value: str = "doing",
    review_value: str = "review",
    done_value: str = "done",
    lease_seconds: int = 7200,
) -> dict[str, object]:
    """Claim every declared flow member with one lease or mutate no member."""
    mapping = flow_mapping_from_arguments(
        row_id_column,
        status_column,
        lease_token_column,
        lease_until_column,
        pr_url_column,
        last_error_column,
        ready_value,
        doing_value,
        review_value,
        done_value,
    )
    return build_flow_queue().claim_flow(
        spreadsheet_id,
        sheet_name,
        mapping,
        flow_id,
        row_ids,
        lease_seconds,
        expected_values,
    )


@mcp.tool()
def expand_flow_claim(
    spreadsheet_id: str,
    sheet_name: str,
    row_id_column: str,
    status_column: str,
    lease_token_column: str,
    lease_until_column: str,
    pr_url_column: str,
    last_error_column: str,
    flow_id: str,
    lease_token: str,
    row_ids: list[str],
    expected_values: dict[str, dict[str, object]],
    ready_value: str = "ready",
    doing_value: str = "doing",
    review_value: str = "review",
    done_value: str = "done",
) -> dict[str, object]:
    """Add newly discovered ready members to an active flow before editing them."""
    mapping = flow_mapping_from_arguments(
        row_id_column,
        status_column,
        lease_token_column,
        lease_until_column,
        pr_url_column,
        last_error_column,
        ready_value,
        doing_value,
        review_value,
        done_value,
    )
    return build_flow_queue().expand_flow_claim(
        spreadsheet_id,
        sheet_name,
        mapping,
        flow_id,
        lease_token,
        row_ids,
        expected_values,
    )


@mcp.tool()
def complete_flow_rows(
    spreadsheet_id: str,
    sheet_name: str,
    row_id_column: str,
    status_column: str,
    lease_token_column: str,
    lease_until_column: str,
    pr_url_column: str,
    last_error_column: str,
    flow_id: str,
    lease_token: str,
    pr_url: str,
    expected_values: dict[str, dict[str, object]],
    ready_value: str = "ready",
    doing_value: str = "doing",
    review_value: str = "review",
    done_value: str = "done",
) -> dict[str, object]:
    """Move every flow member to review with one PR or mutate no member."""
    mapping = flow_mapping_from_arguments(
        row_id_column,
        status_column,
        lease_token_column,
        lease_until_column,
        pr_url_column,
        last_error_column,
        ready_value,
        doing_value,
        review_value,
        done_value,
    )
    return build_flow_queue().complete_flow(
        spreadsheet_id,
        sheet_name,
        mapping,
        flow_id,
        lease_token,
        pr_url,
        expected_values,
    )


@mcp.tool()
def record_flow_error(
    spreadsheet_id: str,
    sheet_name: str,
    row_id_column: str,
    status_column: str,
    lease_token_column: str,
    lease_until_column: str,
    pr_url_column: str,
    last_error_column: str,
    flow_id: str,
    lease_token: str,
    error_code: str,
    expected_values: dict[str, dict[str, object]],
    ready_value: str = "ready",
    doing_value: str = "doing",
    review_value: str = "review",
    done_value: str = "done",
) -> dict[str, object]:
    """Record one controlled error on every active member without releasing the flow."""
    mapping = flow_mapping_from_arguments(
        row_id_column,
        status_column,
        lease_token_column,
        lease_until_column,
        pr_url_column,
        last_error_column,
        ready_value,
        doing_value,
        review_value,
        done_value,
    )
    return build_flow_queue().record_flow_error(
        spreadsheet_id,
        sheet_name,
        mapping,
        flow_id,
        lease_token,
        error_code,
        expected_values,
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
