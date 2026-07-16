#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unicodedata


UTF8_BOM = b"\xef\xbb\xbf"
DELIMITERS = (b",", b"\t", b";", b"|")
ID_ALIASES = ("id", "编号")
TITLE_ALIASES = ("title", "标题")
DESIGN_URL_ALIASES = ("design_url", "设计稿地址")
UI_NOTES_ALIASES = ("ui_notes", "UI补充描述")
INTERACTION_ALIASES = ("interaction", "交互描述")
API_ALIASES = ("api", "接口描述")
STATUS_ALIASES = ("status", "状态")
ERROR_ALIASES = ("error", "错误")
SPEC_DIR_ALIASES = ("spec_dir", "设计产物目录")
VALID_STATUSES = {"", "doing", "done", "error"}


class CsvStatusError(RuntimeError):
    pass


@dataclass(frozen=True)
class Field:
    start: int
    end: int
    value: str
    quoted: bool


@dataclass(frozen=True)
class Document:
    raw: bytes
    bom: bool
    delimiter: bytes
    records: list[list[Field]]
    headers: list[str]
    title_index: int
    status_index: int


def normalized(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def raw_record_fields(data: bytes, start: int, delimiter: int) -> list[list[tuple[int, int]]]:
    records: list[list[tuple[int, int]]] = []
    fields: list[tuple[int, int]] = []
    field_start = start
    in_quotes = False
    index = start
    while index < len(data):
        byte = data[index]
        if in_quotes:
            if byte == 34:
                if index + 1 < len(data) and data[index + 1] == 34:
                    index += 2
                else:
                    in_quotes = False
                    index += 1
            else:
                index += 1
            continue
        if byte == 34 and index == field_start:
            in_quotes = True
            index += 1
        elif byte == delimiter:
            fields.append((field_start, index))
            field_start = index + 1
            index += 1
        elif byte in (10, 13):
            fields.append((field_start, index))
            records.append(fields)
            fields = []
            if byte == 13 and index + 1 < len(data) and data[index + 1] == 10:
                index += 2
            else:
                index += 1
            field_start = index
        else:
            index += 1
    if in_quotes:
        raise CsvStatusError("CSV contains an unterminated quoted field")
    if fields or field_start < len(data):
        fields.append((field_start, len(data)))
        records.append(fields)
    return records


def decode_field(data: bytes, bounds: tuple[int, int]) -> Field:
    start, end = bounds
    raw = data[start:end]
    quoted = len(raw) >= 2 and raw.startswith(b'"') and raw.endswith(b'"')
    if quoted:
        payload = raw[1:-1].replace(b'""', b'"')
    else:
        if b'"' in raw:
            raise CsvStatusError("CSV contains a quote in an unquoted field")
        payload = raw
    try:
        value = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CsvStatusError("CSV must be valid UTF-8, optionally with a UTF-8 BOM") from exc
    return Field(start=start, end=end, value=value, quoted=quoted)


def semantic_index(headers: list[str], aliases: tuple[str, ...], label: str) -> int:
    matches = [index for index, header in enumerate(headers) if normalized(header) in aliases]
    if len(matches) != 1:
        raise CsvStatusError(f"CSV must contain exactly one semantic {label} column; headers={headers!r}")
    return matches[0]


def optional_semantic_index(headers: list[str], aliases: tuple[str, ...], label: str) -> int | None:
    matches = [index for index, header in enumerate(headers) if normalized(header) in aliases]
    if len(matches) > 1:
        raise CsvStatusError(f"CSV must not contain ambiguous semantic {label} columns; headers={headers!r}")
    return matches[0] if matches else None


def parse_document(raw: bytes) -> Document:
    bom = raw.startswith(UTF8_BOM)
    start = len(UTF8_BOM) if bom else 0
    candidates: list[tuple[int, bytes, list[list[tuple[int, int]]]]] = []
    for delimiter in DELIMITERS:
        records = raw_record_fields(raw, start, delimiter[0])
        width = len(records[0]) if records else 0
        candidates.append((width, delimiter, records))
    best_width = max((item[0] for item in candidates), default=0)
    best = [item for item in candidates if item[0] == best_width]
    if best_width < 2 or len(best) != 1:
        raise CsvStatusError("CSV delimiter is missing or ambiguous")
    _, delimiter, raw_records = best[0]
    records = [[decode_field(raw, bounds) for bounds in record] for record in raw_records]
    if not records:
        raise CsvStatusError("CSV is empty")
    headers = [field.value for field in records[0]]
    for row_index, record in enumerate(records[1:], start=1):
        if len(record) != len(headers):
            raise CsvStatusError(
                f"CSV row {row_index} has {len(record)} columns; expected {len(headers)}"
            )
    return Document(
        raw=raw,
        bom=bom,
        delimiter=delimiter,
        records=records,
        headers=headers,
        title_index=semantic_index(headers, TITLE_ALIASES, "title"),
        status_index=semantic_index(headers, STATUS_ALIASES, "status"),
    )


def line_endings(raw: bytes) -> dict[str, int]:
    crlf = raw.count(b"\r\n")
    return {
        "crlf": crlf,
        "lf": raw.count(b"\n") - crlf,
        "cr": raw.count(b"\r") - crlf,
    }


def matching_rows(document: Document, title: str) -> list[tuple[int, list[Field]]]:
    wanted = normalized(title)
    return [
        (row_index, record)
        for row_index, record in enumerate(document.records[1:], start=1)
        if normalized(record[document.title_index].value) == wanted
    ]


def export_csv(
    path: Path,
    title: str,
    expect_status: str,
    output: Path,
    interaction_output: Path | None = None,
    ui_notes_output: Path | None = None,
    api_output: Path | None = None,
) -> dict[str, object]:
    document = parse_document(path.read_bytes())
    matches = matching_rows(document, title)
    if len(matches) != 1:
        raise CsvStatusError(f"title must match exactly one row: {title!r}; matches={len(matches)}")
    row_number, record = matches[0]
    current_status = record[document.status_index].value
    if current_status != expect_status:
        raise CsvStatusError(
            f"status drift for {title!r}: expected {expect_status!r}, found {current_status!r}"
        )

    required = {
        "title": document.title_index,
        "design_url": semantic_index(document.headers, DESIGN_URL_ALIASES, "design_url"),
        "ui_notes": semantic_index(document.headers, UI_NOTES_ALIASES, "ui_notes"),
        "interaction": semantic_index(document.headers, INTERACTION_ALIASES, "interaction"),
        "api": semantic_index(document.headers, API_ALIASES, "api"),
        "status": document.status_index,
    }
    optional = {
        "id": optional_semantic_index(document.headers, ID_ALIASES, "id"),
        "error": optional_semantic_index(document.headers, ERROR_ALIASES, "error"),
        "spec_dir": optional_semantic_index(document.headers, SPEC_DIR_ALIASES, "spec_dir"),
    }
    exported: dict[str, object] = {
        key: record[index].value for key, index in required.items()
    }
    exported.update(
        {key: record[index].value if index is not None else "" for key, index in optional.items()}
    )
    exported["row_number"] = row_number

    field_outputs = {
        "interaction": interaction_output,
        "ui_notes": ui_notes_output,
        "api": api_output,
    }
    for key, field_output in field_outputs.items():
        if field_output is None:
            continue
        field_output.parent.mkdir(parents=True, exist_ok=True)
        field_mode = field_output.stat().st_mode if field_output.exists() else 0o644
        atomic_replace(field_output, str(exported[key]).encode("utf-8"), field_mode)

    output.parent.mkdir(parents=True, exist_ok=True)
    mode = output.stat().st_mode if output.exists() else 0o644
    encoded = (json.dumps(exported, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    atomic_replace(output, encoded, mode)
    return {
        "ok": True,
        "path": str(path),
        "out": str(output),
        "title": title,
        "status": current_status,
        "lengths": {
            key: len(str(exported[key])) for key in ("design_url", "ui_notes", "interaction", "api")
        },
    }


def inspect_csv(path: Path, title: str) -> dict:
    document = parse_document(path.read_bytes())
    matches = matching_rows(document, title)
    return {
        "ok": True,
        "path": str(path.resolve()),
        "format": {
            "encoding": "UTF-8",
            "bom": document.bom,
            "delimiter": document.delimiter.decode("ascii"),
            "lineEndings": line_endings(document.raw),
        },
        "columns": {
            "title": document.headers[document.title_index],
            "status": document.headers[document.status_index],
        },
        "matches": [
            {
                "rowIndex": row_index,
                "title": record[document.title_index].value,
                "status": record[document.status_index].value,
            }
            for row_index, record in matches
        ],
    }


def encoded_replacement(field: Field, value: str, delimiter: bytes) -> bytes:
    payload = value.encode("utf-8")
    escaped = payload.replace(b'"', b'""')
    requires_quotes = any(token in payload for token in (delimiter, b'"', b"\r", b"\n"))
    if field.quoted or requires_quotes:
        return b'"' + escaped + b'"'
    return payload


def lock_path(path: Path) -> Path:
    digest = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:24]
    return Path(tempfile.gettempdir()) / f"iff-csv-row-status-{digest}.lock"


def atomic_replace(path: Path, raw: bytes, mode: int) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.iff-tmp-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, stat.S_IMODE(mode))
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def resolve_column_updates(document: Document, assignments: list[str]) -> list[tuple[int, str, str]]:
    resolved: list[tuple[int, str, str]] = []
    seen: set[int] = set()
    protected = {document.title_index, document.status_index}
    for assignment in assignments:
        if "=" not in assignment:
            raise CsvStatusError("--set-column must use COLUMN=VALUE")
        requested, value = assignment.split("=", 1)
        if not requested:
            raise CsvStatusError("--set-column column name must be non-empty")
        matches = [
            index
            for index, header in enumerate(document.headers)
            if normalized(header) == normalized(requested)
        ]
        if len(matches) != 1:
            raise CsvStatusError(
                f"--set-column must name exactly one existing column: {requested!r}; "
                f"headers={document.headers!r}"
            )
        index = matches[0]
        if index in protected:
            raise CsvStatusError("title/status columns must use their dedicated update arguments")
        if index in seen:
            raise CsvStatusError(f"duplicate --set-column target: {document.headers[index]!r}")
        seen.add(index)
        resolved.append((index, document.headers[index], value))
    return resolved


def update_csv(
    path: Path,
    title: str,
    expected_status: str,
    status_value: str,
    column_assignments: list[str] | None = None,
) -> dict:
    assignments = column_assignments or []
    if expected_status not in VALID_STATUSES or status_value not in VALID_STATUSES:
        raise CsvStatusError("status values must be one of empty, doing, done, or error")
    if expected_status == status_value and not assignments:
        raise CsvStatusError("same-status update requires --set-column")
    if not title:
        raise CsvStatusError("title must be non-empty")
    if path.is_symlink():
        raise CsvStatusError("refusing to atomically replace a symlinked CSV")
    with lock_path(path).open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        metadata = path.stat()
        if not stat.S_ISREG(metadata.st_mode):
            raise CsvStatusError("CSV path must be a regular file")
        document = parse_document(path.read_bytes())
        title_matches = matching_rows(document, title)
        active = [
            item
            for item in title_matches
            if item[1][document.status_index].value == expected_status
        ]
        if len(active) != 1:
            observed = [record[document.status_index].value for _, record in title_matches]
            raise CsvStatusError(
                "expected exactly one active row for "
                f"title={title!r} status={expected_status!r}; titleMatches={len(title_matches)} "
                f"observedStatuses={observed!r}"
            )
        row_index, record = active[0]
        column_updates = resolve_column_updates(document, assignments)
        if expected_status == status_value and all(
            record[index].value == value for index, _header, value in column_updates
        ):
            raise CsvStatusError("metadata update does not change any value")
        replacements = [(document.status_index, status_value)] + [
            (index, value) for index, _header, value in column_updates
        ]
        updated = document.raw
        for index, value in sorted(replacements, key=lambda item: record[item[0]].start, reverse=True):
            field = record[index]
            replacement = encoded_replacement(field, value, document.delimiter)
            updated = updated[: field.start] + replacement + updated[field.end :]
        before_hash = hashlib.sha256(document.raw).hexdigest()
        after_hash = hashlib.sha256(updated).hexdigest()
        atomic_replace(path, updated, metadata.st_mode)
    return {
        "ok": True,
        "path": str(path.resolve()),
        "rowIndex": row_index,
        "titleColumn": document.headers[document.title_index],
        "statusColumn": document.headers[document.status_index],
        "title": record[document.title_index].value,
        "previousStatus": expected_status,
        "status": status_value,
        "updatedColumns": {header: value for _index, header, value in column_updates},
        "sha256Before": before_hash,
        "sha256After": after_hash,
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Inspect or atomically update one semantic iFF CSV row status")
    commands = root.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("--csv", required=True)
    inspect.add_argument("--title", required=True)
    export = commands.add_parser("export")
    export.add_argument("--csv", required=True)
    export.add_argument("--title", required=True)
    export.add_argument("--expect-status", required=True)
    export.add_argument("--out", required=True)
    export.add_argument("--interaction-out")
    export.add_argument("--ui-notes-out")
    export.add_argument("--api-out")
    update = commands.add_parser("update")
    update.add_argument("--csv", required=True)
    update.add_argument("--title", required=True)
    update.add_argument("--expect-status", required=True)
    update.add_argument("--status", required=True)
    update.add_argument(
        "--set-column",
        action="append",
        default=[],
        metavar="COLUMN=VALUE",
        help="atomically update an additional existing column; repeat as needed",
    )
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        path = Path(args.csv)
        if args.command == "inspect":
            result = inspect_csv(path, args.title)
        elif args.command == "export":
            result = export_csv(
                path,
                args.title,
                args.expect_status,
                Path(args.out),
                Path(args.interaction_out) if args.interaction_out else None,
                Path(args.ui_notes_out) if args.ui_notes_out else None,
                Path(args.api_out) if args.api_out else None,
            )
        else:
            result = update_csv(
                path,
                args.title,
                args.expect_status,
                args.status,
                args.set_column,
            )
    except (CsvStatusError, FileNotFoundError, PermissionError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
