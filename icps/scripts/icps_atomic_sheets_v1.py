#!/usr/bin/env python3
from __future__ import annotations

import fcntl
import hashlib
import json
import secrets
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterator, Protocol
from urllib.parse import urlparse


@dataclass(frozen=True)
class QueueMapping:
    row_id: str
    status: str
    lease_token: str
    lease_until: str
    pr_url: str
    ready: str
    doing: str
    done: str
    last_error: str | None = None


@dataclass
class SheetRow:
    row_number: int
    values: dict[str, str]


class SheetStore(Protocol):
    def find_first_row_number(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        column: str,
        value: str,
    ) -> int | None: ...

    def read_row(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        row_number: int,
    ) -> SheetRow: ...

    def update_row(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        row_number: int,
        updates: dict[str, str],
    ) -> SheetRow: ...


def canonical_row_id(value: object) -> str:
    if value is None:
        return ""
    raw = str(value)
    if any(ord(character) < 32 or ord(character) == 127 for character in raw):
        raise ValueError("row identity must not contain control characters")
    return raw.strip()


class AtomicSheetQueue:
    def __init__(
        self,
        store: SheetStore,
        lock_root: Path,
        clock: Callable[[], datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self.store = store
        self.lock_root = lock_root
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.token_factory = token_factory or (lambda: secrets.token_urlsafe(32))

    @contextmanager
    def _locked(self, spreadsheet_id: str, sheet_name: str) -> Iterator[None]:
        self.lock_root.mkdir(parents=True, exist_ok=True)
        identity = hashlib.sha256(
            f"{spreadsheet_id}\0{sheet_name}".encode("utf-8")
        ).hexdigest()
        lock_path = self.lock_root / f"{identity}.lock"
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _locator_path(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        lease_token: str,
    ) -> Path:
        locator_identity = hashlib.sha256(
            f"{spreadsheet_id}\0{sheet_name}\0{lease_token}".encode("utf-8")
        ).hexdigest()
        return self.lock_root / "claims" / f"{locator_identity}.json"

    def _persist_locator(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        row: SheetRow,
        row_id: str,
        lease_token: str,
    ) -> None:
        locator_path = self._locator_path(spreadsheet_id, sheet_name, lease_token)
        locator_path.parent.mkdir(parents=True, exist_ok=True)
        locator = {
            "spreadsheet_id": spreadsheet_id,
            "sheet_name": sheet_name,
            "row_number": row.row_number,
            "row_id": row_id,
            "lease_token": lease_token,
        }
        encoded = json.dumps(locator, ensure_ascii=False, sort_keys=True) + "\n"
        try:
            with locator_path.open("x", encoding="utf-8") as locator_file:
                locator_file.write(encoded)
        except FileExistsError:
            existing = json.loads(locator_path.read_text(encoding="utf-8"))
            if existing != locator:
                raise ValueError("claim locator collision")

    def _read_claimed_row(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        mapping: QueueMapping,
        row_id: str,
        lease_token: str,
    ) -> SheetRow:
        locator_path = self._locator_path(spreadsheet_id, sheet_name, lease_token)
        try:
            locator = json.loads(locator_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ValueError("claim locator is missing") from exc
        expected_locator = {
            "spreadsheet_id": spreadsheet_id,
            "sheet_name": sheet_name,
            "row_id": row_id,
            "lease_token": lease_token,
        }
        if (
            not isinstance(locator, dict)
            or any(locator.get(key) != value for key, value in expected_locator.items())
            or type(locator.get("row_number")) is not int
            or locator["row_number"] < 2
        ):
            raise ValueError("claim locator is invalid")
        selected = self.store.read_row(
            spreadsheet_id,
            sheet_name,
            locator["row_number"],
        )
        if canonical_row_id(selected.values.get(mapping.row_id)) != row_id:
            raise ValueError("claimed row identity drift")
        return selected

    def claim(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        mapping: QueueMapping,
        lease_seconds: int,
    ) -> dict[str, object]:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        with self._locked(spreadsheet_id, sheet_name):
            row_number = self.store.find_first_row_number(
                spreadsheet_id,
                sheet_name,
                mapping.status,
                mapping.ready,
            )
            if row_number is None:
                return {"status": "no-work"}
            selected = self.store.read_row(spreadsheet_id, sheet_name, row_number)
            if selected.values.get(mapping.status) != mapping.ready:
                raise ValueError("selected row is no longer ready")
            row_id = canonical_row_id(selected.values.get(mapping.row_id))
            if not row_id:
                raise ValueError("selected row identity is missing")

            lease_token = self.token_factory()
            if not isinstance(lease_token, str) or not lease_token:
                raise ValueError("lease token factory returned an invalid token")
            lease_until = self.clock() + timedelta(seconds=lease_seconds)
            updates = {
                mapping.status: mapping.doing,
                mapping.lease_token: lease_token,
                mapping.lease_until: lease_until.astimezone(timezone.utc)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z"),
            }
            if mapping.last_error is not None:
                updates[mapping.last_error] = ""
            self._persist_locator(
                spreadsheet_id,
                sheet_name,
                selected,
                row_id,
                lease_token,
            )
            updated = self.store.update_row(
                spreadsheet_id,
                sheet_name,
                selected.row_number,
                updates,
            )
            return {
                "status": "claimed",
                "row_number": updated.row_number,
                "row": updated.values,
            }

    def complete(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        mapping: QueueMapping,
        row_id: str,
        lease_token: str,
        pr_url: str,
        expected_values: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if any(ord(character) < 32 or ord(character) == 127 for character in pr_url):
            raise ValueError("PR URL contains control characters")
        parsed_pr_url = urlparse(pr_url)
        if parsed_pr_url.scheme not in {"http", "https"} or not parsed_pr_url.hostname:
            raise ValueError("PR URL must be an absolute HTTP or HTTPS URL")
        with self._locked(spreadsheet_id, sheet_name):
            selected = self._read_claimed_row(
                spreadsheet_id,
                sheet_name,
                mapping,
                row_id,
                lease_token,
            )
            if expected_values is not None and (
                not isinstance(expected_values, dict)
                or not expected_values
                or any(
                    not isinstance(column, str) or not column
                    for column in expected_values
                )
            ):
                raise ValueError("expected row values are invalid")
            terminal_mutations = {
                mapping.status,
                mapping.pr_url,
                mapping.lease_token,
                mapping.lease_until,
            }
            if mapping.last_error is not None:
                terminal_mutations.add(mapping.last_error)
            terminal_guard_matches = expected_values is None or all(
                selected.values.get(column) == expected
                for column, expected in expected_values.items()
                if column not in terminal_mutations
            )
            terminal_error_clear = (
                mapping.last_error is None
                or selected.values.get(mapping.last_error) in {"", None}
            )
            if (
                selected.values.get(mapping.status) == mapping.done
                and selected.values.get(mapping.pr_url) == pr_url
                and selected.values.get(mapping.lease_token) in {"", None}
                and selected.values.get(mapping.lease_until) in {"", None}
                and terminal_error_clear
                and terminal_guard_matches
            ):
                return {
                    "status": "done",
                    "row_status": mapping.done,
                    "row_number": selected.row_number,
                    "row": selected.values,
                    "reconstructed": True,
                }
            if selected.values.get(mapping.status) != mapping.doing:
                raise ValueError("claimed row is not doing")
            if selected.values.get(mapping.lease_token) != lease_token:
                raise ValueError("claimed row lease mismatch")
            if expected_values is not None:
                if (
                    not isinstance(expected_values, dict)
                    or not expected_values
                    or any(
                        not isinstance(column, str) or not column
                        for column in expected_values
                    )
                ):
                    raise ValueError("expected row values are invalid")
                if any(
                    selected.values.get(column) != expected
                    for column, expected in expected_values.items()
                ):
                    raise ValueError("row input drift")
            updates = {
                mapping.pr_url: pr_url,
                mapping.status: mapping.done,
                mapping.lease_token: "",
                mapping.lease_until: "",
            }
            if mapping.last_error is not None:
                updates[mapping.last_error] = ""
            updated = self.store.update_row(
                spreadsheet_id,
                sheet_name,
                selected.row_number,
                updates,
            )
            return {
                "status": "done",
                "row_status": mapping.done,
                "row_number": updated.row_number,
                "row": updated.values,
                "reconstructed": False,
            }

    def record_error(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        mapping: QueueMapping,
        row_id: str,
        lease_token: str,
        error_code: str,
        expected_values: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if mapping.last_error is None:
            raise ValueError("last_error column is not configured")
        if (
            not isinstance(error_code, str)
            or not error_code
            or len(error_code) > 129
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in error_code
            )
        ):
            raise ValueError("error code is invalid")
        with self._locked(spreadsheet_id, sheet_name):
            selected = self._read_claimed_row(
                spreadsheet_id,
                sheet_name,
                mapping,
                row_id,
                lease_token,
            )
            if selected.values.get(mapping.status) != mapping.doing:
                raise ValueError("claimed row is not doing")
            if selected.values.get(mapping.lease_token) != lease_token:
                raise ValueError("claimed row lease mismatch")
            if expected_values is not None:
                if (
                    not isinstance(expected_values, dict)
                    or not expected_values
                    or any(
                        not isinstance(column, str) or not column
                        for column in expected_values
                    )
                ):
                    raise ValueError("expected row values are invalid")
                if any(
                    selected.values.get(column) != expected
                    for column, expected in expected_values.items()
                ):
                    raise ValueError("row input drift")
            updated = self.store.update_row(
                spreadsheet_id,
                sheet_name,
                selected.row_number,
                {mapping.last_error: error_code},
            )
            return {
                "status": "error-recorded",
                "row_number": updated.row_number,
                "row": updated.values,
            }
