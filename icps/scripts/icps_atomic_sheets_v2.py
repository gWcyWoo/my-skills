#!/usr/bin/env python3
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import secrets
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterator, Protocol
from urllib.parse import urlparse

from icps_atomic_sheets_v1 import SheetRow, canonical_row_id


@dataclass(frozen=True)
class FlowQueueMapping:
    row_id: str
    status: str
    lease_token: str
    lease_until: str
    pr_url: str
    last_error: str
    ready: str
    doing: str
    review: str
    done: str


class FlowSheetStore(Protocol):
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

    def find_row_numbers_by_ids(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        column: str,
        row_ids: list[str],
    ) -> dict[str, int]: ...

    def list_row_ids(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        column: str,
    ) -> list[str]: ...

    def read_rows(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        row_numbers: list[int],
    ) -> list[SheetRow]: ...

    def update_rows(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        updates: dict[int, dict[str, str]],
    ) -> list[SheetRow]: ...


class AtomicSheetFlowQueue:
    def __init__(
        self,
        store: FlowSheetStore,
        lock_root: Path,
        clock: Callable[[], datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self.store = store
        self.lock_root = lock_root
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.token_factory = token_factory or (lambda: secrets.token_urlsafe(32))

    @staticmethod
    def _validate_expected_values(
        mapping: FlowQueueMapping,
        row_ids: list[str],
        expected_values: dict[str, dict[str, object]],
    ) -> None:
        if not isinstance(expected_values, dict) or set(expected_values) != set(row_ids):
            raise ValueError("flow expected values do not cover every member")
        mutable_columns = {
            mapping.status,
            mapping.lease_token,
            mapping.lease_until,
            mapping.last_error,
        }
        if any(
            not isinstance(row_guards, dict)
            or not row_guards
            or any(
                not isinstance(column, str)
                or not column
                or column in mutable_columns
                for column in row_guards
            )
            for row_guards in expected_values.values()
        ):
            raise ValueError("flow expected values are invalid")

    @staticmethod
    def _guard_digests(
        expected_values: dict[str, dict[str, object]],
    ) -> dict[str, str]:
        try:
            return {
                row_id: hashlib.sha256(
                    json.dumps(
                        row_guards,
                        ensure_ascii=False,
                        allow_nan=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                for row_id, row_guards in expected_values.items()
            }
        except (TypeError, ValueError) as exc:
            raise ValueError("flow expected values are invalid") from exc

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
        self, spreadsheet_id: str, sheet_name: str, flow_id: str
    ) -> Path:
        identity = hashlib.sha256(
            f"{spreadsheet_id}\0{sheet_name}\0{flow_id}".encode("utf-8")
        ).hexdigest()
        return self.lock_root / "flow-claims" / f"{identity}.json"

    def _released_locator_path(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        flow_id: str,
        lease_token: str,
    ) -> Path:
        flow_identity = hashlib.sha256(
            f"{spreadsheet_id}\0{sheet_name}\0{flow_id}".encode("utf-8")
        ).hexdigest()
        lease_identity = hashlib.sha256(lease_token.encode("utf-8")).hexdigest()
        return (
            self.lock_root
            / "flow-claim-releases"
            / flow_identity
            / f"{lease_identity}.json"
        )

    def _persist_locator(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        flow_id: str,
        lease_token: str,
        lease_until: str,
        rows: list[SheetRow],
        row_ids: list[str],
        guard_digests: dict[str, str],
    ) -> None:
        path = self._locator_path(spreadsheet_id, sheet_name, flow_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        locator = {
            "kind": "icps.flow-claim-locator.v2",
            "schema_version": 2,
            "spreadsheet_id": spreadsheet_id,
            "sheet_name": sheet_name,
            "flow_id": flow_id,
            "lease_token": lease_token,
            "lease_until": lease_until,
            "phase": "claim-prepared",
            "guard_digests": guard_digests,
            "members": [
                {"row_id": row_id, "row_number": row.row_number}
                for row_id, row in zip(row_ids, rows, strict=True)
            ],
            "pending_expansion": [],
            "pending_guard_digests": {},
        }
        encoded = json.dumps(locator, ensure_ascii=False, sort_keys=True) + "\n"
        try:
            with path.open("x", encoding="utf-8") as stream:
                stream.write(encoded)
        except FileExistsError as exc:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != locator:
                raise ValueError("flow claim locator collision") from exc

    def _load_locator(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        flow_id: str,
        *,
        path: Path | None = None,
        allowed_phases: set[str] | None = None,
    ) -> dict[str, object]:
        path = path or self._locator_path(spreadsheet_id, sheet_name, flow_id)
        allowed_phases = allowed_phases or {"claim-prepared", "claimed"}
        try:
            locator = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ValueError("flow claim locator is missing") from exc
        expected = {
            "kind": "icps.flow-claim-locator.v2",
            "schema_version": 2,
            "spreadsheet_id": spreadsheet_id,
            "sheet_name": sheet_name,
            "flow_id": flow_id,
        }
        if (
            not isinstance(locator, dict)
            or any(locator.get(key) != value for key, value in expected.items())
            or not isinstance(locator.get("lease_token"), str)
            or not locator["lease_token"]
            or not isinstance(locator.get("lease_until"), str)
            or not locator["lease_until"]
            or locator.get("phase") not in allowed_phases
            or not isinstance(locator.get("guard_digests"), dict)
            or not isinstance(locator.get("members"), list)
            or not locator["members"]
            or not isinstance(locator.get("pending_expansion"), list)
            or not isinstance(locator.get("pending_guard_digests"), dict)
        ):
            raise ValueError("flow claim locator is invalid")
        members = locator["members"]
        assert isinstance(members, list)
        if any(
            not isinstance(member, dict)
            or set(member) != {"row_id", "row_number"}
            or not isinstance(member["row_id"], str)
            or not member["row_id"]
            or type(member["row_number"]) is not int
            or member["row_number"] < 2
            for member in members
        ):
            raise ValueError("flow claim locator is invalid")
        row_ids = [member["row_id"] for member in members]
        row_numbers = [member["row_number"] for member in members]
        if len(row_ids) != len(set(row_ids)) or len(row_numbers) != len(set(row_numbers)):
            raise ValueError("flow claim locator is invalid")
        guard_digests = locator["guard_digests"]
        assert isinstance(guard_digests, dict)
        if set(guard_digests) != set(row_ids) or any(
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            for digest in guard_digests.values()
        ):
            raise ValueError("flow claim locator is invalid")
        pending = locator["pending_expansion"]
        assert isinstance(pending, list)
        if any(
            not isinstance(member, dict)
            or set(member) != {"row_id", "row_number"}
            or not isinstance(member["row_id"], str)
            or not member["row_id"]
            or type(member["row_number"]) is not int
            or member["row_number"] < 2
            for member in pending
        ):
            raise ValueError("flow claim locator is invalid")
        pending_ids = [member["row_id"] for member in pending]
        pending_numbers = [member["row_number"] for member in pending]
        if (
            len(pending_ids) != len(set(pending_ids))
            or len(pending_numbers) != len(set(pending_numbers))
            or set(pending_ids).intersection(row_ids)
            or set(pending_numbers).intersection(row_numbers)
            or (pending and locator["phase"] != "claimed")
        ):
            raise ValueError("flow claim locator is invalid")
        pending_guard_digests = locator["pending_guard_digests"]
        assert isinstance(pending_guard_digests, dict)
        if set(pending_guard_digests) != set(pending_ids) or any(
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            for digest in pending_guard_digests.values()
        ):
            raise ValueError("flow claim locator is invalid")
        return locator

    def _replace_locator(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        flow_id: str,
        locator: dict[str, object],
    ) -> None:
        path = self._locator_path(spreadsheet_id, sheet_name, flow_id)
        temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".next")
        temporary.write_text(
            json.dumps(locator, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)

    def inspect_ready_root(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        mapping: FlowQueueMapping,
    ) -> dict[str, object]:
        with self._locked(spreadsheet_id, sheet_name):
            row_number = self.store.find_first_row_number(
                spreadsheet_id,
                sheet_name,
                mapping.status,
                mapping.ready,
            )
            if row_number is None:
                return {"status": "no-work"}
            row = self.store.read_row(spreadsheet_id, sheet_name, row_number)
            if row.values.get(mapping.status) != mapping.ready:
                raise ValueError("selected flow root is no longer ready")
            if not canonical_row_id(row.values.get(mapping.row_id)):
                raise ValueError("selected flow root identity is missing")
            return {
                "kind": "icps.flow-root-inspection.v2",
                "schema_version": 2,
                "status": "ready-root",
                "row_number": row.row_number,
                "row": row.values,
            }

    def inspect_title_catalog(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        mapping: FlowQueueMapping,
    ) -> dict[str, object]:
        with self._locked(spreadsheet_id, sheet_name):
            titles = self.store.list_row_ids(
                spreadsheet_id, sheet_name, mapping.row_id
            )
            if not titles:
                raise ValueError("flow title catalog is empty")
            canonical_titles = [canonical_row_id(title) for title in titles]
            if any(not title for title in canonical_titles):
                raise ValueError("flow title catalog contains an empty identity")
            if len(canonical_titles) != len(set(canonical_titles)):
                raise ValueError("flow title catalog contains duplicate identities")
            payload = {
                "spreadsheet_id": spreadsheet_id,
                "sheet_name": sheet_name,
                "row_id_column": mapping.row_id,
                "titles": canonical_titles,
            }
            return {
                "kind": "icps.flow-title-catalog.v1",
                "schema_version": 1,
                **payload,
                "catalog_digest": hashlib.sha256(
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        allow_nan=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
            }

    def inspect_flow_rows(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        mapping: FlowQueueMapping,
        row_ids: list[str],
    ) -> dict[str, object]:
        if (
            not isinstance(row_ids, list)
            or not row_ids
            or len(row_ids) != len(set(row_ids))
            or any(canonical_row_id(row_id) != row_id or not row_id for row_id in row_ids)
        ):
            raise ValueError("flow row identities are invalid")
        with self._locked(spreadsheet_id, sheet_name):
            row_numbers = self.store.find_row_numbers_by_ids(
                spreadsheet_id,
                sheet_name,
                mapping.row_id,
                row_ids,
            )
            if set(row_numbers) != set(row_ids):
                raise ValueError("flow member row is missing or duplicated")
            rows = self.store.read_rows(
                spreadsheet_id,
                sheet_name,
                [row_numbers[row_id] for row_id in row_ids],
            )
            for row_id, row in zip(row_ids, rows, strict=True):
                if canonical_row_id(row.values.get(mapping.row_id)) != row_id:
                    raise ValueError("flow member identity drift")
            return {
                "kind": "icps.flow-row-inspection.v2",
                "schema_version": 2,
                "status": "inspected",
                "row_ids": row_ids,
                "rows": [row.values for row in rows],
            }

    def release_flow_claim(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        mapping: FlowQueueMapping,
        flow_id: str,
        lease_token: str,
        expected_values: dict[str, dict[str, object]],
    ) -> dict[str, object]:
        if (
            not isinstance(flow_id, str)
            or not flow_id
            or any(ord(character) < 32 or ord(character) == 127 for character in flow_id)
        ):
            raise ValueError("flow identity is invalid")
        if not isinstance(lease_token, str) or not lease_token:
            raise ValueError("lease token is invalid")

        with self._locked(spreadsheet_id, sheet_name):
            active_path = self._locator_path(spreadsheet_id, sheet_name, flow_id)
            archive_path = self._released_locator_path(
                spreadsheet_id,
                sheet_name,
                flow_id,
                lease_token,
            )
            if not active_path.exists():
                released_locator = self._load_locator(
                    spreadsheet_id,
                    sheet_name,
                    flow_id,
                    path=archive_path,
                    allowed_phases={"released"},
                )
                if released_locator["lease_token"] != lease_token:
                    raise ValueError("flow lease token mismatch")
                released_members = released_locator["members"]
                assert isinstance(released_members, list)
                released_row_ids = [
                    str(member["row_id"]) for member in released_members
                ]
                self._validate_expected_values(
                    mapping,
                    released_row_ids,
                    expected_values,
                )
                if released_locator["guard_digests"] != self._guard_digests(
                    expected_values
                ):
                    raise ValueError(
                        "flow expected values do not match release archive"
                    )
                released_rows = self.store.read_rows(
                    spreadsheet_id,
                    sheet_name,
                    [int(member["row_number"]) for member in released_members],
                )
                for row_id, row in zip(
                    released_row_ids,
                    released_rows,
                    strict=True,
                ):
                    if canonical_row_id(row.values.get(mapping.row_id)) != row_id:
                        raise ValueError("flow member identity drift")
                    if any(
                        row.values.get(column) != expected
                        for column, expected in expected_values[row_id].items()
                    ):
                        raise ValueError("flow member input drift")
                    if (
                        row.values.get(mapping.status) != mapping.ready
                        or row.values.get(mapping.lease_token) not in {"", None}
                        or row.values.get(mapping.lease_until) not in {"", None}
                        or row.values.get(mapping.last_error) not in {"", None}
                    ):
                        raise ValueError("released flow member state drift")
                return {
                    "kind": "icps.flow-release-result.v2",
                    "schema_version": 2,
                    "status": "released",
                    "flow_id": flow_id,
                    "member_row_ids": released_row_ids,
                    "rows": [row.values for row in released_rows],
                    "reconstructed": True,
                }

            locator = self._load_locator(
                spreadsheet_id,
                sheet_name,
                flow_id,
                allowed_phases={"claim-prepared", "claimed", "released"},
            )
            if locator["pending_expansion"]:
                raise ValueError("flow claim has a pending expansion")
            if locator["lease_token"] != lease_token:
                raise ValueError("flow lease token mismatch")
            members = locator["members"]
            assert isinstance(members, list)
            row_ids = [str(member["row_id"]) for member in members]
            self._validate_expected_values(mapping, row_ids, expected_values)
            if locator["guard_digests"] != self._guard_digests(expected_values):
                raise ValueError("flow expected values do not match claim locator")

            if archive_path.exists():
                raise ValueError("flow release archive already exists")

            selected = self.store.read_rows(
                spreadsheet_id,
                sheet_name,
                [int(member["row_number"]) for member in members],
            )
            lease_until = str(locator["lease_until"])
            already_restored = True
            for row_id, row in zip(row_ids, selected, strict=True):
                if canonical_row_id(row.values.get(mapping.row_id)) != row_id:
                    raise ValueError("flow member identity drift")
                if any(
                    row.values.get(column) != expected
                    for column, expected in expected_values[row_id].items()
                ):
                    raise ValueError("flow member input drift")
                owned = (
                    row.values.get(mapping.status) == mapping.doing
                    and row.values.get(mapping.lease_token) == lease_token
                    and row.values.get(mapping.lease_until) == lease_until
                )
                recoverable_ready = (
                    row.values.get(mapping.status) == mapping.ready
                    and row.values.get(mapping.lease_token)
                    in {lease_token, "", None}
                    and row.values.get(mapping.lease_until)
                    in {lease_until, "", None}
                )
                restored = (
                    recoverable_ready
                    and row.values.get(mapping.lease_token) in {"", None}
                    and row.values.get(mapping.lease_until) in {"", None}
                    and row.values.get(mapping.last_error) in {"", None}
                )
                if not owned and not recoverable_ready:
                    raise ValueError("flow member is not owned by release lease")
                already_restored = already_restored and restored

            if already_restored:
                released_rows = selected
            else:
                released_rows = self.store.update_rows(
                    spreadsheet_id,
                    sheet_name,
                    {
                        row.row_number: {
                            mapping.status: mapping.ready,
                            mapping.lease_token: "",
                            mapping.lease_until: "",
                            mapping.last_error: "",
                        }
                        for row in selected
                    },
                )
            if len(released_rows) != len(row_ids):
                raise ValueError("flow release acknowledgement drift")
            for row_id, row in zip(row_ids, released_rows, strict=True):
                if (
                    canonical_row_id(row.values.get(mapping.row_id)) != row_id
                    or any(
                        row.values.get(column) != expected
                        for column, expected in expected_values[row_id].items()
                    )
                    or row.values.get(mapping.status) != mapping.ready
                    or row.values.get(mapping.lease_token) not in {"", None}
                    or row.values.get(mapping.lease_until) not in {"", None}
                    or row.values.get(mapping.last_error) not in {"", None}
                ):
                    raise ValueError("flow release acknowledgement drift")
            released_at = self.clock().astimezone(timezone.utc).isoformat(
                timespec="seconds"
            ).replace("+00:00", "Z")
            released_locator = {
                **locator,
                "phase": "released",
                "released_at": released_at,
            }
            self._replace_locator(
                spreadsheet_id,
                sheet_name,
                flow_id,
                released_locator,
            )
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(active_path, archive_path)
            return {
                "kind": "icps.flow-release-result.v2",
                "schema_version": 2,
                "status": "released",
                "flow_id": flow_id,
                "member_row_ids": row_ids,
                "rows": [row.values for row in released_rows],
                "reconstructed": already_restored,
            }

    def claim_flow(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        mapping: FlowQueueMapping,
        flow_id: str,
        row_ids: list[str],
        lease_seconds: int,
        expected_values: dict[str, dict[str, object]],
    ) -> dict[str, object]:
        if (
            not isinstance(flow_id, str)
            or not flow_id
            or any(ord(character) < 32 or ord(character) == 127 for character in flow_id)
        ):
            raise ValueError("flow identity is invalid")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if (
            not isinstance(row_ids, list)
            or not row_ids
            or len(row_ids) != len(set(row_ids))
        ):
            raise ValueError("flow row identities are invalid")
        canonical_ids = [canonical_row_id(row_id) for row_id in row_ids]
        if canonical_ids != row_ids or any(not row_id for row_id in canonical_ids):
            raise ValueError("flow row identities are invalid")
        self._validate_expected_values(mapping, row_ids, expected_values)
        guard_digests = self._guard_digests(expected_values)

        with self._locked(spreadsheet_id, sheet_name):
            locator_path = self._locator_path(spreadsheet_id, sheet_name, flow_id)
            if locator_path.exists():
                locator = self._load_locator(spreadsheet_id, sheet_name, flow_id)
                if locator["pending_expansion"]:
                    raise ValueError("flow claim has a pending expansion")
                members = locator["members"]
                assert isinstance(members, list)
                if [member["row_id"] for member in members] != row_ids:
                    raise ValueError("existing flow claim membership mismatch")
                if locator["guard_digests"] != guard_digests:
                    raise ValueError("flow expected values do not match claim locator")
                selected = self.store.read_rows(
                    spreadsheet_id,
                    sheet_name,
                    [int(member["row_number"]) for member in members],
                )
                lease_token = str(locator["lease_token"])
                lease_until = str(locator["lease_until"])
                live_states: set[str] = set()
                for row_id, row in zip(row_ids, selected, strict=True):
                    if canonical_row_id(row.values.get(mapping.row_id)) != row_id:
                        raise ValueError("flow member identity drift")
                    if any(
                        row.values.get(column) != expected
                        for column, expected in expected_values[row_id].items()
                    ):
                        raise ValueError("flow member input drift")
                    if (
                        row.values.get(mapping.status) == mapping.doing
                        and row.values.get(mapping.lease_token) == lease_token
                        and row.values.get(mapping.lease_until) == lease_until
                    ):
                        live_states.add("claimed")
                    elif (
                        row.values.get(mapping.status) == mapping.ready
                        and row.values.get(mapping.lease_token) in {"", None}
                        and row.values.get(mapping.lease_until) in {"", None}
                    ):
                        live_states.add("ready")
                    else:
                        raise ValueError("persisted flow member state drift")
                if len(live_states) != 1:
                    raise ValueError("persisted flow members are partially claimed")
                live_state = next(iter(live_states))
                if live_state == "ready":
                    if locator["phase"] != "claim-prepared":
                        raise ValueError("claimed flow unexpectedly returned to ready")
                    selected = self.store.update_rows(
                        spreadsheet_id,
                        sheet_name,
                        {
                            row.row_number: {
                                mapping.status: mapping.doing,
                                mapping.lease_token: lease_token,
                                mapping.lease_until: lease_until,
                                mapping.last_error: "",
                            }
                            for row in selected
                        },
                    )
                    self._replace_locator(
                        spreadsheet_id,
                        sheet_name,
                        flow_id,
                        {**locator, "phase": "claimed"},
                    )
                    reconstructed = False
                else:
                    if locator["phase"] != "claimed":
                        self._replace_locator(
                            spreadsheet_id,
                            sheet_name,
                            flow_id,
                            {**locator, "phase": "claimed"},
                        )
                    reconstructed = True
                return {
                    "kind": "icps.flow-claim-result.v2",
                    "schema_version": 2,
                    "status": "claimed",
                    "flow_id": flow_id,
                    "lease_token": lease_token,
                    "lease_until": lease_until,
                    "rows": [row.values for row in selected],
                    "reconstructed": reconstructed,
                }
            row_numbers = self.store.find_row_numbers_by_ids(
                spreadsheet_id,
                sheet_name,
                mapping.row_id,
                row_ids,
            )
            if set(row_numbers) != set(row_ids):
                raise ValueError("flow member row is missing or duplicated")
            selected = self.store.read_rows(
                spreadsheet_id,
                sheet_name,
                [row_numbers[row_id] for row_id in row_ids],
            )
            for row_id, row in zip(row_ids, selected, strict=True):
                if canonical_row_id(row.values.get(mapping.row_id)) != row_id:
                    raise ValueError("flow member identity drift")
                if row.values.get(mapping.status) != mapping.ready:
                    raise ValueError("flow member is not ready")
                if any(
                    row.values.get(column) != expected
                    for column, expected in expected_values[row_id].items()
                ):
                    raise ValueError("flow member input drift")

            lease_token = self.token_factory()
            if not isinstance(lease_token, str) or not lease_token:
                raise ValueError("lease token factory returned an invalid token")
            lease_until = (self.clock() + timedelta(seconds=lease_seconds)).astimezone(
                timezone.utc
            ).isoformat(timespec="seconds").replace("+00:00", "Z")
            self._persist_locator(
                spreadsheet_id,
                sheet_name,
                flow_id,
                lease_token,
                lease_until,
                selected,
                row_ids,
                guard_digests,
            )
            updates = {
                row.row_number: {
                    mapping.status: mapping.doing,
                    mapping.lease_token: lease_token,
                    mapping.lease_until: lease_until,
                    mapping.last_error: "",
                }
                for row in selected
            }
            updated = self.store.update_rows(
                spreadsheet_id,
                sheet_name,
                updates,
            )
            locator = self._load_locator(spreadsheet_id, sheet_name, flow_id)
            self._replace_locator(
                spreadsheet_id,
                sheet_name,
                flow_id,
                {**locator, "phase": "claimed"},
            )
            return {
                "kind": "icps.flow-claim-result.v2",
                "schema_version": 2,
                "status": "claimed",
                "flow_id": flow_id,
                "lease_token": lease_token,
                "lease_until": lease_until,
                "rows": [row.values for row in updated],
                "reconstructed": False,
            }

    def expand_flow_claim(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        mapping: FlowQueueMapping,
        flow_id: str,
        lease_token: str,
        row_ids: list[str],
        expected_values: dict[str, dict[str, object]],
    ) -> dict[str, object]:
        if (
            not isinstance(row_ids, list)
            or not row_ids
            or len(row_ids) != len(set(row_ids))
            or any(canonical_row_id(row_id) != row_id or not row_id for row_id in row_ids)
        ):
            raise ValueError("flow expansion row identities are invalid")
        self._validate_expected_values(mapping, row_ids, expected_values)
        guard_digests = self._guard_digests(expected_values)
        with self._locked(spreadsheet_id, sheet_name):
            locator = self._load_locator(spreadsheet_id, sheet_name, flow_id)
            if locator["lease_token"] != lease_token:
                raise ValueError("flow claim lease mismatch")
            if locator["phase"] != "claimed":
                raise ValueError("flow claim is not committed")
            members = locator["members"]
            assert isinstance(members, list)
            member_ids = [str(member["row_id"]) for member in members]
            overlapping_ids = set(member_ids).intersection(row_ids)
            existing_rows = self.store.read_rows(
                spreadsheet_id,
                sheet_name,
                [int(member["row_number"]) for member in members],
            )
            lease_until = str(locator["lease_until"])
            for member, row in zip(members, existing_rows, strict=True):
                if canonical_row_id(row.values.get(mapping.row_id)) != member["row_id"]:
                    raise ValueError("flow member identity drift")
                if row.values.get(mapping.status) != mapping.doing:
                    raise ValueError("flow member is not doing")
                if row.values.get(mapping.lease_token) != lease_token:
                    raise ValueError("flow claim lease mismatch")
                if row.values.get(mapping.lease_until) != lease_until:
                    raise ValueError("flow member lease expiry mismatch")
            pending = locator["pending_expansion"]
            assert isinstance(pending, list)
            if pending:
                pending_ids = [str(member["row_id"]) for member in pending]
                if pending_ids != row_ids:
                    raise ValueError("flow expansion has a different pending membership")
                if locator["pending_guard_digests"] != guard_digests:
                    raise ValueError("flow expected values do not match claim locator")
                pending_rows = self.store.read_rows(
                    spreadsheet_id,
                    sheet_name,
                    [int(member["row_number"]) for member in pending],
                )
                pending_states: set[str] = set()
                for row_id, row in zip(row_ids, pending_rows, strict=True):
                    if canonical_row_id(row.values.get(mapping.row_id)) != row_id:
                        raise ValueError("flow member identity drift")
                    if any(
                        row.values.get(column) != expected
                        for column, expected in expected_values[row_id].items()
                    ):
                        raise ValueError("flow member input drift")
                    if (
                        row.values.get(mapping.status) == mapping.doing
                        and row.values.get(mapping.lease_token) == lease_token
                        and row.values.get(mapping.lease_until) == lease_until
                    ):
                        pending_states.add("claimed")
                    elif (
                        row.values.get(mapping.status) == mapping.ready
                        and row.values.get(mapping.lease_token) in {"", None}
                        and row.values.get(mapping.lease_until) in {"", None}
                    ):
                        pending_states.add("ready")
                    else:
                        raise ValueError("pending flow expansion state drift")
                if len(pending_states) != 1:
                    raise ValueError("pending flow expansion is partially claimed")
                pending_state = next(iter(pending_states))
                if pending_state == "ready":
                    pending_rows = self.store.update_rows(
                        spreadsheet_id,
                        sheet_name,
                        {
                            row.row_number: {
                                mapping.status: mapping.doing,
                                mapping.lease_token: lease_token,
                                mapping.lease_until: lease_until,
                                mapping.last_error: "",
                            }
                            for row in pending_rows
                        },
                    )
                    reconstructed = False
                else:
                    reconstructed = True
                finalized_members = [*members, *pending]
                self._replace_locator(
                    spreadsheet_id,
                    sheet_name,
                    flow_id,
                    {
                        **locator,
                        "members": finalized_members,
                        "pending_expansion": [],
                        "guard_digests": {
                            **locator["guard_digests"],
                            **locator["pending_guard_digests"],
                        },
                        "pending_guard_digests": {},
                    },
                )
                return {
                    "kind": "icps.flow-expand-result.v2",
                    "schema_version": 2,
                    "status": "expanded",
                    "flow_id": flow_id,
                    "lease_token": lease_token,
                    "member_row_ids": [*member_ids, *row_ids],
                    "rows": [row.values for row in pending_rows],
                    "reconstructed": reconstructed,
                }
            if set(row_ids).issubset(member_ids):
                committed_guard_digests = locator["guard_digests"]
                assert isinstance(committed_guard_digests, dict)
                if any(
                    committed_guard_digests[row_id] != guard_digests[row_id]
                    for row_id in row_ids
                ):
                    raise ValueError("flow expected values do not match claim locator")
                rows_by_id = {
                    str(member["row_id"]): row
                    for member, row in zip(members, existing_rows, strict=True)
                }
                for row_id in row_ids:
                    row = rows_by_id[row_id]
                    if any(
                        row.values.get(column) != expected
                        for column, expected in expected_values[row_id].items()
                    ):
                        raise ValueError("flow member input drift")
                return {
                    "kind": "icps.flow-expand-result.v2",
                    "schema_version": 2,
                    "status": "expanded",
                    "flow_id": flow_id,
                    "lease_token": lease_token,
                    "member_row_ids": member_ids,
                    "rows": [rows_by_id[row_id].values for row_id in row_ids],
                    "reconstructed": True,
                }
            if overlapping_ids:
                raise ValueError("flow expansion membership is ambiguous")

            row_numbers = self.store.find_row_numbers_by_ids(
                spreadsheet_id,
                sheet_name,
                mapping.row_id,
                row_ids,
            )
            if set(row_numbers) != set(row_ids):
                raise ValueError("flow expansion row is missing or duplicated")
            new_rows = self.store.read_rows(
                spreadsheet_id,
                sheet_name,
                [row_numbers[row_id] for row_id in row_ids],
            )
            for row_id, row in zip(row_ids, new_rows, strict=True):
                if canonical_row_id(row.values.get(mapping.row_id)) != row_id:
                    raise ValueError("flow member identity drift")
                if row.values.get(mapping.status) != mapping.ready:
                    raise ValueError("flow expansion member is not ready")
                if any(
                    row.values.get(column) != expected
                    for column, expected in expected_values[row_id].items()
                ):
                    raise ValueError("flow member input drift")

            pending_members = [
                {"row_id": row_id, "row_number": row.row_number}
                for row_id, row in zip(row_ids, new_rows, strict=True)
            ]
            self._replace_locator(
                spreadsheet_id,
                sheet_name,
                flow_id,
                {
                    **locator,
                    "pending_expansion": pending_members,
                    "pending_guard_digests": guard_digests,
                },
            )
            updated = self.store.update_rows(
                spreadsheet_id,
                sheet_name,
                {
                    row.row_number: {
                        mapping.status: mapping.doing,
                        mapping.lease_token: lease_token,
                        mapping.lease_until: lease_until,
                        mapping.last_error: "",
                    }
                    for row in new_rows
                },
            )
            finalized_members = [*members, *pending_members]
            self._replace_locator(
                spreadsheet_id,
                sheet_name,
                flow_id,
                {
                    **locator,
                    "members": finalized_members,
                    "pending_expansion": [],
                    "guard_digests": {
                        **locator["guard_digests"],
                        **guard_digests,
                    },
                    "pending_guard_digests": {},
                },
            )
            return {
                "kind": "icps.flow-expand-result.v2",
                "schema_version": 2,
                "status": "expanded",
                "flow_id": flow_id,
                "lease_token": lease_token,
                "member_row_ids": [*member_ids, *row_ids],
                "rows": [row.values for row in updated],
                "reconstructed": False,
            }

    def complete_flow(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        mapping: FlowQueueMapping,
        flow_id: str,
        lease_token: str,
        pr_url: str | None,
        expected_values: dict[str, dict[str, object]],
    ) -> dict[str, object]:
        if pr_url is not None:
            if any(ord(character) < 32 or ord(character) == 127 for character in pr_url):
                raise ValueError("PR URL contains control characters")
            parsed_pr = urlparse(pr_url)
            if parsed_pr.scheme not in {"http", "https"} or not parsed_pr.hostname:
                raise ValueError("PR URL must be an absolute HTTP or HTTPS URL")
        if not isinstance(expected_values, dict) or not expected_values:
            raise ValueError("flow expected values are invalid")
        with self._locked(spreadsheet_id, sheet_name):
            locator = self._load_locator(spreadsheet_id, sheet_name, flow_id)
            if locator["lease_token"] != lease_token:
                raise ValueError("flow claim lease mismatch")
            if locator["phase"] != "claimed" or locator["pending_expansion"]:
                raise ValueError("flow claim is not stable")
            members = locator["members"]
            assert isinstance(members, list)
            member_ids = [str(member["row_id"]) for member in members]
            self._validate_expected_values(mapping, member_ids, expected_values)
            if locator["guard_digests"] != self._guard_digests(expected_values):
                raise ValueError("flow expected values do not match claim locator")
            selected = self.store.read_rows(
                spreadsheet_id,
                sheet_name,
                [int(member["row_number"]) for member in members],
            )
            for member, row in zip(members, selected, strict=True):
                row_id = str(member["row_id"])
                if canonical_row_id(row.values.get(mapping.row_id)) != row_id:
                    raise ValueError("flow member identity drift")
            terminal_matches = all(
                row.values.get(mapping.status) == mapping.review
                and (pr_url is None or row.values.get(mapping.pr_url) == pr_url)
                and row.values.get(mapping.lease_token) in {"", None}
                and row.values.get(mapping.lease_until) in {"", None}
                and row.values.get(mapping.last_error) in {"", None}
                for row in selected
            )
            if terminal_matches:
                for member, row in zip(members, selected, strict=True):
                    row_id = str(member["row_id"])
                    if any(
                        (pr_url is None or column != mapping.pr_url)
                        and row.values.get(column) != expected
                        for column, expected in expected_values[row_id].items()
                    ):
                        raise ValueError("flow member input drift")
                return {
                    "kind": "icps.flow-completion-result.v2",
                    "schema_version": 2,
                    "status": "review",
                    "flow_id": flow_id,
                    "pr_url": pr_url,
                    "member_row_ids": member_ids,
                    "rows": [row.values for row in selected],
                    "reconstructed": True,
                }
            for member, row in zip(members, selected, strict=True):
                row_id = str(member["row_id"])
                if any(
                    row.values.get(column) != expected
                    for column, expected in expected_values[row_id].items()
                ):
                    raise ValueError("flow member input drift")
                if row.values.get(mapping.status) != mapping.doing:
                    raise ValueError("flow member is not doing")
                if row.values.get(mapping.lease_token) != lease_token:
                    raise ValueError("flow claim lease mismatch")
            terminal_updates = {
                mapping.status: mapping.review,
                mapping.lease_token: "",
                mapping.lease_until: "",
                mapping.last_error: "",
            }
            if pr_url is not None:
                terminal_updates[mapping.pr_url] = pr_url
            updated = self.store.update_rows(
                spreadsheet_id,
                sheet_name,
                {
                    row.row_number: terminal_updates
                    for row in selected
                },
            )
            return {
                "kind": "icps.flow-completion-result.v2",
                "schema_version": 2,
                "status": "review",
                "flow_id": flow_id,
                "pr_url": pr_url,
                "member_row_ids": member_ids,
                "rows": [row.values for row in updated],
                "reconstructed": False,
            }

    def record_flow_error(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        mapping: FlowQueueMapping,
        flow_id: str,
        lease_token: str,
        error_code: str,
        expected_values: dict[str, dict[str, object]],
    ) -> dict[str, object]:
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
            locator = self._load_locator(spreadsheet_id, sheet_name, flow_id)
            if locator["lease_token"] != lease_token:
                raise ValueError("flow claim lease mismatch")
            if locator["phase"] != "claimed" or locator["pending_expansion"]:
                raise ValueError("flow claim is not stable")
            members = locator["members"]
            assert isinstance(members, list)
            member_ids = [str(member["row_id"]) for member in members]
            self._validate_expected_values(mapping, member_ids, expected_values)
            if locator["guard_digests"] != self._guard_digests(expected_values):
                raise ValueError("flow expected values do not match claim locator")
            selected = self.store.read_rows(
                spreadsheet_id,
                sheet_name,
                [int(member["row_number"]) for member in members],
            )
            for member, row in zip(members, selected, strict=True):
                row_id = str(member["row_id"])
                if canonical_row_id(row.values.get(mapping.row_id)) != row_id:
                    raise ValueError("flow member identity drift")
                if row.values.get(mapping.status) != mapping.doing:
                    raise ValueError("flow member is not doing")
                if row.values.get(mapping.lease_token) != lease_token:
                    raise ValueError("flow claim lease mismatch")
                if any(
                    row.values.get(column) != expected
                    for column, expected in expected_values[row_id].items()
                ):
                    raise ValueError("flow member input drift")
            updated = self.store.update_rows(
                spreadsheet_id,
                sheet_name,
                {
                    row.row_number: {mapping.last_error: error_code}
                    for row in selected
                },
            )
            return {
                "kind": "icps.flow-error-result.v2",
                "schema_version": 2,
                "status": "error-recorded",
                "flow_id": flow_id,
                "member_row_ids": member_ids,
                "rows": [row.values for row in updated],
            }
