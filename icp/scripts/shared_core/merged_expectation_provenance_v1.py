"""Platform-neutral merged-expectation provenance contract — v1.

P2.5c adds exactly one new platform-neutral contract to SharedCore: a
provenance document that records the digest chain by which the frozen trace
consumer's *effective* expected document was assembled. The real iFF trace
flow first creates ``merged_expected.json`` from the raw canvas expectation,
``shared_components.local.json``, and ``scene.json``; ``gen_layout_trace_test.py``
also silently adopts an adjacent merged file when only a raw canvas sidecar is
supplied. Therefore gating the trace directly on the raw projection (P2.5a1/a2/b)
would prove file A while the frozen consumer uses effective document B.

This contract closes that gap by recording the digest chain:

  * ``pageCanvasProjectionSha256`` — the raw page canvas projection (the
    document P2.5a1/a2/b materializes and projects);
  * ``sharedComponentsLocalSha256`` — ``shared_components.local.json`` (or
    ``null`` when the frozen merge producer's missing-local pass-through
    path was taken);
  * ``sceneSha256`` — the page ``scene.json`` (bbox source for the merge);
  * ``mergedExpectedSha256`` — the produced ``merged_expected.json``;
  * ``pageCanvasNodeIds`` — the page canvas node-id list (insertion order);
  * ``sharedComponentNodeIds`` — the shared-component source-row node-id
    list the merge added (insertion order);
  * ``mergedNodeIds`` — exactly ``pageCanvasNodeIds + sharedComponentNodeIds``
    in order, matching the ``merged_expected.json`` node order.

The contract intentionally records a digest/provenance chain. It does NOT
claim that the raw projection v1 can represent merged shared-component nodes,
and it does NOT reproduce iFF merge behavior in SharedCore. P2.5d binds the
producer/adapter/consumer after this contract is accepted; P2.5c defines
the platform-neutral schema and its proof only.

This module is intentionally pure: it has no CLI, performs no filesystem I/O,
makes no network or process calls, accepts no path/root override, sets no
bytecode flag, and never imports a platform module, the iFF v1 compatibility
capsule, or the P2.5a1 projection module. A future platform producer
(P2.5d) is responsible for producing the document from its own
already-computed state; SharedCore does not recompute the merge.

The canonical byte form is contractually::

    json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")

with no sorted keys, fixed insertion order (the contract's top-level key
order), and no trailing newline. Node-id list insertion order is contractual
and preserved; node ids are not normalized or reordered.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

__all__ = [
    "KIND",
    "SCHEMA_VERSION",
    "MergedExpectationProvenanceError",
    "build_provenance",
    "validate_provenance",
    "build_provenance_bytes",
]

KIND = "icp.shared.merged-expectation-provenance.v1"
SCHEMA_VERSION = 1

# Exact top-level key order is contractual. Every emitter MUST preserve it
# verbatim. The list order is the canonical serialization order.
_TOP_LEVEL_KEYS: tuple[str, ...] = (
    "kind",
    "schemaVersion",
    "producerKind",
    "producerSha256",
    "pageCanvasProjectionSha256",
    "sharedComponentsLocalSha256",
    "sceneSha256",
    "mergedExpectedSha256",
    "pageCanvasNodeIds",
    "sharedComponentNodeIds",
    "mergedNodeIds",
)
_TOP_LEVEL_KEY_SET: frozenset[str] = frozenset(_TOP_LEVEL_KEYS)

# Every digest is exactly 64 lowercase hexadecimal characters.
_DIGEST_RE = re.compile(r"\A[0-9a-f]{64}\Z")

# producerKind: starts with a lowercase letter, followed by 0..127 chars in
# [a-z0-9._-]. The grammar is ASCII-only, so UTF-8 length equals char length
# and is bounded by 128 bytes.
_PRODUCER_KIND_RE = re.compile(r"\A[a-z][a-z0-9._-]{0,127}\Z")

_MAX_NODE_IDS_PER_LIST: int = 100000
_MAX_NODE_ID_UTF8_BYTES: int = 512
_MAX_CANONICAL_BYTES: int = 32 * 1024 * 1024


class MergedExpectationProvenanceError(ValueError):
    """Raised when a merged-expectation provenance document violates the v1 contract."""


# ---------------------------------------------------------------------------
# Tiny type guards (centralized so every check uses identical semantics).
# ---------------------------------------------------------------------------


def _safe_repr(value: Any) -> str:
    """Render any value's repr without letting a failing ``__repr__`` escape.

    A custom object whose ``__repr__`` raises would otherwise leak its
    exception through error-message construction. This helper calls
    ``repr`` exactly once and falls back to a deterministic type-name form
    on any failure, so message construction is itself fail-closed.
    """
    try:
        return repr(value)
    except Exception:  # noqa: BLE001 — defensive formatting only
        return f"<{type(value).__name__} unrenderable>"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MergedExpectationProvenanceError(message)


def _classify_mapping_keys(
    mapping: Mapping[Any, Any], allowed: frozenset[str],
) -> tuple[list[str], list[str], list[str]]:
    """Materialize mapping keys into (missing, unknown_string, bad_keys) groups.

    Every object key is validated to be a string BEFORE any set arithmetic,
    so a custom hashable key with a failing ``__repr__`` is reported via
    :class:`MergedExpectationProvenanceError` rather than crashing message
    construction. Bad keys are rendered with :func:`_safe_repr` which never
    calls a failing repr twice.

    Returns three lists (deterministic, sorted by ``repr``):
      * ``missing`` — keys in ``allowed`` but absent from ``mapping``;
      * ``unknown_string`` — string keys not in ``allowed``;
      * ``bad_keys`` — renderings of any non-string keys.
    """
    missing: list[str] = []
    unknown_string: list[str] = []
    bad_keys: list[str] = []
    present_strings: set[str] = set()
    try:
        keys = list(mapping.keys())
    except Exception as exc:  # noqa: BLE001 — hostile Mapping.keys()
        raise MergedExpectationProvenanceError(
            f"provenance root mapping keys() failed: {type(exc).__name__}: {exc}"
        ) from exc
    for key in keys:
        if isinstance(key, str):
            present_strings.add(key)
        else:
            bad_keys.append(_safe_repr(key))
    for allowed_key in allowed:
        if allowed_key not in present_strings:
            missing.append(allowed_key)
    for key in present_strings:
        if key not in allowed:
            unknown_string.append(key)
    missing.sort()
    unknown_string.sort()
    bad_keys.sort()
    return missing, unknown_string, bad_keys


def _validate_digest(value: Any, field: str) -> None:
    """Require ``value`` to be exactly 64 lowercase hex chars."""
    _require(
        isinstance(value, str),
        f"{field} must be a 64-lowercase-hex string: got {_safe_repr(value)}",
    )
    _require(
        _DIGEST_RE.match(value) is not None,
        f"{field} must be exactly 64 lowercase hex chars: got {_safe_repr(value)}",
    )


def _validate_optional_digest(value: Any, field: str) -> None:
    """Like :func:`_validate_digest` but also accepts ``None`` (the frozen
    merge producer's missing-local pass-through case)."""
    if value is None:
        return
    _validate_digest(value, field)


def _validate_producer_kind(value: Any) -> None:
    _require(
        isinstance(value, str),
        f"producerKind must be a string: got {_safe_repr(value)}",
    )
    _require(
        _PRODUCER_KIND_RE.match(value) is not None,
        f"producerKind must match ^[a-z][a-z0-9._-]{{0,127}}$: "
        f"got {_safe_repr(value)}",
    )


def _validate_node_id_list(value: Any, field: str) -> list[str]:
    """Validate a node-id list and return a detached plain ``list`` of the
    string ids in insertion order.

    Rejects: non-list, custom sequence subclasses that are not ``list``,
    non-string items, empty strings, ids exceeding 512 UTF-8 bytes, ids
    containing ASCII control characters (0x00-0x1F or 0x7F), duplicate ids,
    and lists longer than 100000 entries.
    """
    _require(
        isinstance(value, list),
        f"{field} must be a JSON array: got {_safe_repr(value)}",
    )
    seen: set[str] = set()
    out: list[str] = []
    index = 0
    for index, item in enumerate(value):
        _require(
            isinstance(item, str),
            f"{field}[{index}] must be a string: got {_safe_repr(item)}",
        )
        _require(
            item != "",
            f"{field}[{index}] must be a non-empty string",
        )
        # UTF-8 byte bound (not char count).
        try:
            utf8_len = len(item.encode("utf-8"))
        except UnicodeError as exc:  # defensive: pure str never raises here
            raise MergedExpectationProvenanceError(
                f"{field}[{index}] is not UTF-8 encodable: {exc}"
            ) from exc
        _require(
            utf8_len <= _MAX_NODE_ID_UTF8_BYTES,
            f"{field}[{index}] exceeds {_MAX_NODE_ID_UTF8_BYTES} UTF-8 bytes "
            f"(got {utf8_len})",
        )
        # No ASCII control characters: 0x00-0x1F or 0x7F.
        _require(
            not any(ord(ch) < 32 or ord(ch) == 127 for ch in item),
            f"{field}[{index}] contains ASCII control characters",
        )
        _require(
            item not in seen,
            f"{field}[{index}] duplicates earlier id: {_safe_repr(item)}",
        )
        seen.add(item)
        out.append(item)
    _require(
        len(out) <= _MAX_NODE_IDS_PER_LIST,
        f"{field} has {len(out)} entries; maximum is {_MAX_NODE_IDS_PER_LIST}",
    )
    return out


# ---------------------------------------------------------------------------
# Validation + detached clone.
# ---------------------------------------------------------------------------


def validate_provenance(value: Mapping[str, object]) -> dict[str, object]:
    """Validate a merged-expectation provenance document and return a
    detached plain-built-in clone in the canonical top-level key order.

    Accepts any :class:`typing.Mapping` whose keys are exactly the
    contractual top-level set. The returned document is a fresh ``dict``
    (never the caller's Mapping subclass) containing fresh ``list``
    instances for each node-id field (never the caller's sequence
    subclass). Mutating the caller's input after this call does not
    change the returned document.

    Canonical byte bound: the canonical encoded output (see
    :func:`build_provenance_bytes`) is verified to be at most 32 MiB.

    Raises :class:`MergedExpectationProvenanceError` on any contract
    violation (and only that exception).
    """
    _require(
        isinstance(value, Mapping),
        f"provenance root must be a JSON object: got {type(value).__name__}",
    )
    missing, unknown_string, bad_keys = _classify_mapping_keys(
        value, _TOP_LEVEL_KEY_SET,
    )
    _require(
        not missing and not unknown_string and not bad_keys,
        f"provenance top-level keys must be exactly {_TOP_LEVEL_KEYS}; "
        f"missing={missing} unknown={unknown_string} bad_keys={bad_keys}",
    )

    kind = value["kind"]
    _require(
        kind == KIND,
        f"kind must be {KIND!r}: got {_safe_repr(kind)}",
    )

    schema_version = value["schemaVersion"]
    _require(
        isinstance(schema_version, int)
        and not isinstance(schema_version, bool)
        and schema_version == SCHEMA_VERSION,
        f"schemaVersion must be int {SCHEMA_VERSION} (bool is not int): "
        f"got {_safe_repr(schema_version)}",
    )

    producer_kind = value["producerKind"]
    _validate_producer_kind(producer_kind)

    _validate_digest(value["producerSha256"], "producerSha256")
    _validate_digest(
        value["pageCanvasProjectionSha256"], "pageCanvasProjectionSha256",
    )
    _validate_optional_digest(
        value["sharedComponentsLocalSha256"], "sharedComponentsLocalSha256",
    )
    _validate_digest(value["sceneSha256"], "sceneSha256")
    _validate_digest(value["mergedExpectedSha256"], "mergedExpectedSha256")

    page_ids = _validate_node_id_list(
        value["pageCanvasNodeIds"], "pageCanvasNodeIds",
    )
    shared_ids = _validate_node_id_list(
        value["sharedComponentNodeIds"], "sharedComponentNodeIds",
    )
    merged_ids = _validate_node_id_list(
        value["mergedNodeIds"], "mergedNodeIds",
    )

    # Page and shared sets must be disjoint.
    page_set = set(page_ids)
    shared_set = set(shared_ids)
    overlap = page_set & shared_set
    _require(
        not overlap,
        f"pageCanvasNodeIds and sharedComponentNodeIds must be disjoint; "
        f"overlap={sorted(overlap)}",
    )

    # mergedNodeIds must equal page + shared in exact order.
    expected_merged = page_ids + shared_ids
    _require(
        merged_ids == expected_merged,
        "mergedNodeIds must equal pageCanvasNodeIds + sharedComponentNodeIds "
        "in exact order (including the empty-shared case)",
    )

    # Build the detached plain-built-in clone in canonical key order.
    # Strings are immutable; re-attaching references is safe. Lists are
    # rebuilt as plain ``list`` instances so a caller's sequence subclass
    # is never serialized downstream.
    detached: dict[str, object] = {
        "kind": KIND,
        "schemaVersion": SCHEMA_VERSION,
        "producerKind": producer_kind,
        "producerSha256": value["producerSha256"],
        "pageCanvasProjectionSha256": value["pageCanvasProjectionSha256"],
        "sharedComponentsLocalSha256": value["sharedComponentsLocalSha256"],
        "sceneSha256": value["sceneSha256"],
        "mergedExpectedSha256": value["mergedExpectedSha256"],
        "pageCanvasNodeIds": page_ids,
        "sharedComponentNodeIds": shared_ids,
        "mergedNodeIds": merged_ids,
    }

    # Verify the canonical byte bound. ``allow_nan=False`` is defensive:
    # the schema has only str/int/None/list[str] values, so NaN/Inf can
    # never appear, but using allow_nan=False keeps the contract honest
    # if a future field ever carries a float.
    canonical = json.dumps(
        detached, ensure_ascii=False, indent=2, allow_nan=False,
    ).encode("utf-8")
    _require(
        len(canonical) <= _MAX_CANONICAL_BYTES,
        f"canonical encoded provenance exceeds {_MAX_CANONICAL_BYTES} bytes "
        f"(got {len(canonical)})",
    )

    return detached


def build_provenance(
    *,
    producerKind: str,
    producerSha256: str,
    pageCanvasProjectionSha256: str,
    sharedComponentsLocalSha256: str | None,
    sceneSha256: str,
    mergedExpectedSha256: str,
    pageCanvasNodeIds: list[str],
    sharedComponentNodeIds: list[str],
    mergedNodeIds: list[str],
) -> dict[str, object]:
    """Construct a merged-expectation provenance document from keyword-only
    values, then validate it.

    The ``kind`` and ``schemaVersion`` fields are fixed by the contract
    and are not caller-supplied. Every variable field is keyword-only so
    callers cannot accidentally transpose positional digest arguments.

    Raises :class:`MergedExpectationProvenanceError` on any contract
    violation (and only that exception).
    """
    doc: dict[str, object] = {
        "kind": KIND,
        "schemaVersion": SCHEMA_VERSION,
        "producerKind": producerKind,
        "producerSha256": producerSha256,
        "pageCanvasProjectionSha256": pageCanvasProjectionSha256,
        "sharedComponentsLocalSha256": sharedComponentsLocalSha256,
        "sceneSha256": sceneSha256,
        "mergedExpectedSha256": mergedExpectedSha256,
        "pageCanvasNodeIds": pageCanvasNodeIds,
        "sharedComponentNodeIds": sharedComponentNodeIds,
        "mergedNodeIds": mergedNodeIds,
    }
    return validate_provenance(doc)


def build_provenance_bytes(value: Mapping[str, object]) -> bytes:
    """Validate a merged-expectation provenance document and return the
    canonical byte form.

    The byte form is exactly::

        json.dumps(document, ensure_ascii=False, indent=2,
                   allow_nan=False).encode("utf-8")

    with no sorted keys and no trailing newline. ``value`` is validated
    through :func:`validate_provenance`; only the detached validated
    document is serialized, so a caller's Mapping/list subclass is never
    serialized directly and mutating the input after the call does not
    change the bytes a re-decode would yield.

    Raises :class:`MergedExpectationProvenanceError` on any contract
    violation (and only that exception).
    """
    detached = validate_provenance(value)
    return json.dumps(
        detached, ensure_ascii=False, indent=2, allow_nan=False,
    ).encode("utf-8")
