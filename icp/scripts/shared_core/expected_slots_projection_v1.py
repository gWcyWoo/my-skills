"""Platform-neutral expected/slots projection contract — v1.

P2.5a1 adds exactly one new contract to SharedCore: this module. SharedCore
owns only:

  1. strict validation of a platform-neutral *projection* of the design
     intermediate state;
  2. deterministic construction of the legacy ``.expected.json`` and
     ``.slots.json`` documents;
  3. byte serialization exactly matching the frozen legacy JSON sidecars
     emitted by the iFF v1 compatibility capsule.

This module is intentionally pure: it has no CLI, performs no filesystem I/O,
makes no network or process calls, accepts no path/root override, and never
imports a platform module or the iFF v1 compatibility capsule. A future
platform adapter is responsible for producing the projection from its own
already-computed intermediate state; SharedCore does not recompute layout or
codegen.

The legacy byte form is contractually::

    json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")

with no sorted keys and no trailing newline. Reconstruction preserves the
projection's node insertion order: node/list insertion order is contractual.
"""

from __future__ import annotations

import json
import math
from typing import Any, Mapping

__all__ = [
    "KIND",
    "SCHEMA_VERSION",
    "ProjectionValidationError",
    "build_documents",
    "build_legacy_bytes",
    "build_projection_bytes",
]

KIND = "icp.shared.expected-slots-projection.v1"
SCHEMA_VERSION = 1

_TOP_LEVEL_KEYS = (
    "kind",
    "schemaVersion",
    "artboardWidth",
    "artboardHeight",
    "designPixelScale",
    "nodes",
)
_TOP_LEVEL_KEY_SET = frozenset(_TOP_LEVEL_KEYS)

_NODE_KEYS = (
    "id",
    "bbox",
    "horizontalAnchor",
    "impl",
    "text",
    "sourceText",
    "textRuns",
    "fontSize",
    "weight",
    "colorHex",
    "radius",
    "slot",
)
_NODE_KEY_SET = frozenset(_NODE_KEYS)

_EXPECTED_DOC_KEYS = (
    "artboardWidth",
    "artboardHeight",
    "designPixelScale",
    "logicalDesignWidth",
    "nodes",
)
_EXPECTED_NODE_KEYS = (
    "bbox",
    "logicalBbox",
    "horizontalAnchor",
    "impl",
    "text",
    "sourceText",
    "textRuns",
    "fontSize",
    "weight",
    "colorHex",
    "radius",
)

# The projection contract's canonical top-level and per-node key orders
# are exactly ``_TOP_LEVEL_KEYS`` and ``_NODE_KEYS`` (defined below).
# They are part of the contract: every emitter (Flutter adapter, fixture
# guard, and any future platform) MUST preserve them verbatim, and the
# node-list order is the projection's insertion order (NOT a sorted order).


class ProjectionValidationError(ValueError):
    """Raised when an expected/slots projection violates the v1 contract."""


# ---------------------------------------------------------------------------
# Tiny type guards (centralized so every check uses identical semantics).
# ---------------------------------------------------------------------------


def _is_finite_number(value: Any) -> bool:
    """True iff value is a non-bool int/float that is finite (not NaN/inf)."""
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def _is_str_or_none(value: Any) -> bool:
    return value is None or isinstance(value, str)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProjectionValidationError(message)


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


def _classify_mapping_keys(
    mapping: Mapping[str, Any], allowed: frozenset[str],
) -> tuple[list[str], list[str], list[str]]:
    """Materialize mapping keys into (missing, unknown_string, bad_keys) groups.

    Every object key is validated to be a string BEFORE any set arithmetic,
    so a custom hashable key with a failing ``__repr__`` is reported via
    :class:`ProjectionValidationError` rather than crashing message
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
    for key in mapping.keys():
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


def _strict_json_clone(value: Any, path: str) -> Any:
    """Recursively validate that ``value`` is strict JSON and return a detached
    built clone preserving insertion order.

    Accepts only: ``None``, ``bool``, ``str``, finite non-bool ``int``/``float``,
    ``list`` (recursively), and ``Mapping`` with all-string keys (recursively).

    Rejects with :class:`ProjectionValidationError`: NaN, positive/negative
    infinity, ``bytes``, ``tuple``, ``set``, frozenset, custom objects,
    non-string mapping keys, cyclic containers, and any other non-JSON Python
    type.

    Cycle detection uses an active-recursion-path set of container
    ``id``s. When a list or mapping identity is encountered again on the
    active path, a deterministic ``ProjectionValidationError`` is raised. The
    identity is removed in a ``finally`` block so repeated-but-acyclic
    references in sibling branches (ordinary DAG reuse) remain valid.

    The returned clone shares no mutable nested container with the input, so
    callers can freely mutate either side without aliasing leaks. List and
    mapping insertion order is preserved.
    """
    return _strict_json_clone_impl(value, path, set())


def _strict_json_clone_impl(value: Any, path: str, active: set[int]) -> Any:
    """Implementation of :func:`_strict_json_clone` carrying the active-path
    set of container ids. Callers use :func:`_strict_json_clone` which seeds
    a fresh empty set per top-level invocation (no global mutable state, no
    mutable default argument)."""
    if value is None:
        return None
    # bool must be checked before int because bool is a subclass of int.
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ProjectionValidationError(
                f"{path}: NaN/infinity are not strict JSON: got {value!r}"
            )
        return value
    if isinstance(value, list):
        if id(value) in active:
            raise ProjectionValidationError(
                f"{path}: cyclic JSON container is not valid JSON "
                f"(list identity revisited on active recursion path)"
            )
        active.add(id(value))
        try:
            return [_strict_json_clone_impl(item, f"{path}[{index}]", active)
                    for index, item in enumerate(value)]
        finally:
            active.discard(id(value))
    if isinstance(value, Mapping):
        if id(value) in active:
            raise ProjectionValidationError(
                f"{path}: cyclic JSON container is not valid JSON "
                f"(object identity revisited on active recursion path)"
            )
        active.add(id(value))
        try:
            clone: dict[str, Any] = {}
            for key, sub in value.items():
                if not isinstance(key, str):
                    raise ProjectionValidationError(
                        f"{path}: JSON object keys must be strings: got {_safe_repr(key)}"
                    )
                clone[key] = _strict_json_clone_impl(sub, f"{path}.{key}", active)
            return clone
        finally:
            active.discard(id(value))
    raise ProjectionValidationError(
        f"{path}: value is not strict JSON: "
        f"got {type(value).__name__} {_safe_repr(value)}"
    )


# ---------------------------------------------------------------------------
# Validation.
# ---------------------------------------------------------------------------


def _validate_projection(projection: Any) -> None:
    """Validate the projection in one strict pass.

    Rejects: non-mapping root; missing/unknown top-level keys (including
    non-string unknown keys — never leaks a raw ``TypeError`` or a custom
    ``__repr__`` exception); wrong kind or schemaVersion; non-finite/
    non-positive dimensions; non-positive scale; booleans where numbers are
    expected; NaN/infinity anywhere a number is required; ``nodes`` not a
    list; node not an object; missing/unknown node fields; non-string/empty/
    duplicate ids; invalid bbox length or items; non-object/empty anchors;
    wrong impl/text/sourceText/textRuns/fontSize/weight/colorHex/radius
    types; non-strict-JSON nested values inside ``horizontalAnchor`` and
    ``textRuns`` (NaN/infinity, bytes, tuples, sets, custom objects,
    non-string mapping keys, cyclic containers); slot not a boolean;
    ``slot:true`` on a non-text node or with non-string text.
    """
    _require(
        isinstance(projection, Mapping),
        "projection root must be a JSON object",
    )
    missing, unknown_string, bad_keys = _classify_mapping_keys(
        projection, _TOP_LEVEL_KEY_SET,
    )
    _require(
        not missing and not unknown_string and not bad_keys,
        f"projection top-level keys must be exactly {_TOP_LEVEL_KEYS}; "
        f"missing={missing} unknown={unknown_string} bad_keys={bad_keys}",
    )

    _require(
        projection["kind"] == KIND,
        f"projection.kind must be {KIND!r}: got {projection['kind']!r}",
    )
    schema_version = projection["schemaVersion"]
    _require(
        isinstance(schema_version, int)
        and not isinstance(schema_version, bool)
        and schema_version == SCHEMA_VERSION,
        f"projection.schemaVersion must be int {SCHEMA_VERSION}: "
        f"got {schema_version!r}",
    )

    width = projection["artboardWidth"]
    height = projection["artboardHeight"]
    scale = projection["designPixelScale"]
    _require(
        _is_finite_number(width) and width > 0,
        f"projection.artboardWidth must be a finite positive number: got {width!r}",
    )
    _require(
        _is_finite_number(height) and height > 0,
        f"projection.artboardHeight must be a finite positive number: got {height!r}",
    )
    _require(
        _is_finite_number(scale) and scale > 0,
        f"projection.designPixelScale must be a finite positive number: got {scale!r}",
    )

    nodes = projection["nodes"]
    _require(isinstance(nodes, list), "projection.nodes must be a JSON array")

    seen_ids: set[str] = set()
    for index, node in enumerate(nodes):
        _require(
            isinstance(node, Mapping),
            f"projection.nodes[{index}] must be a JSON object",
        )
        missing, unknown_string, bad_keys = _classify_mapping_keys(
            node, _NODE_KEY_SET,
        )
        _require(
            not missing and not unknown_string and not bad_keys,
            f"projection.nodes[{index}] keys must be exactly {_NODE_KEYS}; "
            f"missing={missing} unknown={unknown_string} bad_keys={bad_keys}",
        )

        nid = node["id"]
        _require(
            isinstance(nid, str) and nid != "",
            f"projection.nodes[{index}].id must be a non-empty string: got {nid!r}",
        )
        _require(
            nid not in seen_ids,
            f"projection.nodes[{index}].id duplicates earlier id: {nid!r}",
        )
        seen_ids.add(nid)

        bbox = node["bbox"]
        _require(
            isinstance(bbox, list) and len(bbox) == 4,
            f"projection.nodes[{index}].bbox must be a 4-number list: got {bbox!r}",
        )
        for value in bbox:
            _require(
                _is_finite_number(value),
                f"projection.nodes[{index}].bbox must contain only finite numbers: "
                f"got {value!r} in {bbox!r}",
            )

        anchor = node["horizontalAnchor"]
        _require(
            isinstance(anchor, Mapping) and len(anchor) > 0,
            f"projection.nodes[{index}].horizontalAnchor must be a non-empty JSON object: "
            f"got {anchor!r}",
        )
        # Recursively validate every nested value as strict JSON (rejects
        # NaN/infinity, bytes, tuples, sets, custom objects, non-string keys).
        _strict_json_clone(
            anchor,
            f"projection.nodes[{index}].horizontalAnchor",
        )

        impl = node["impl"]
        _require(
            impl is None or isinstance(impl, str),
            f"projection.nodes[{index}].impl must be a string or null: got {impl!r}",
        )
        _require(
            _is_str_or_none(node["text"]),
            f"projection.nodes[{index}].text must be a string or null: got {node['text']!r}",
        )
        _require(
            _is_str_or_none(node["sourceText"]),
            f"projection.nodes[{index}].sourceText must be a string or null: "
            f"got {node['sourceText']!r}",
        )
        _require(
            isinstance(node["textRuns"], list),
            f"projection.nodes[{index}].textRuns must be a JSON array: "
            f"got {node['textRuns']!r}",
        )
        # Recursively validate every nested value as strict JSON.
        _strict_json_clone(
            node["textRuns"],
            f"projection.nodes[{index}].textRuns",
        )

        font_size = node["fontSize"]
        _require(
            font_size is None or _is_finite_number(font_size),
            f"projection.nodes[{index}].fontSize must be a finite number or null: "
            f"got {font_size!r}",
        )

        weight = node["weight"]
        _require(
            weight is None or isinstance(weight, str) or _is_finite_number(weight),
            f"projection.nodes[{index}].weight must be a finite number, string, or null: "
            f"got {weight!r}",
        )

        _require(
            _is_str_or_none(node["colorHex"]),
            f"projection.nodes[{index}].colorHex must be a string or null: "
            f"got {node['colorHex']!r}",
        )

        radius = node["radius"]
        _require(
            radius is None
            or _is_finite_number(radius)
            or (isinstance(radius, list) and all(_is_finite_number(v) for v in radius)),
            f"projection.nodes[{index}].radius must be a finite number, JSON array of finite "
            f"numbers, or null: got {radius!r}",
        )

        slot = node["slot"]
        _require(
            isinstance(slot, bool),
            f"projection.nodes[{index}].slot must be a boolean: got {slot!r}",
        )
        if slot:
            _require(
                impl == "text",
                f"projection.nodes[{index}].slot=true requires impl=='text': got {impl!r}",
            )
            _require(
                isinstance(node["text"], str),
                f"projection.nodes[{index}].slot=true requires string text: "
                f"got {node['text']!r}",
            )


# ---------------------------------------------------------------------------
# Legacy document reconstruction.
# ---------------------------------------------------------------------------


def _build_expected_node(node: Mapping[str, Any], scale: float) -> dict[str, Any]:
    bbox = list(node["bbox"])
    logical_bbox = [round(float(value) / scale, 2) for value in bbox]
    # Detach nested mutable values via strict-JSON clone so the returned
    # document shares no mutable nested container with the caller's projection.
    # The clone is idempotent on already-validated values (validation ran in
    # _validate_projection before this function is called).
    anchor_clone = _strict_json_clone(node["horizontalAnchor"], "horizontalAnchor")
    runs_clone = _strict_json_clone(node["textRuns"], "textRuns")
    radius = node["radius"]
    if isinstance(radius, list):
        radius = list(radius)  # shallow detach; elements are immutable numbers
    # Construct an ordered dict literal so key order is contractual and static.
    return {
        "bbox": bbox,
        "logicalBbox": logical_bbox,
        "horizontalAnchor": anchor_clone,
        "impl": node["impl"],
        "text": node["text"],
        "sourceText": node["sourceText"],
        "textRuns": runs_clone,
        "fontSize": node["fontSize"],
        "weight": node["weight"],
        "colorHex": node["colorHex"],
        "radius": radius,
    }


def build_documents(
    projection: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    """Build the legacy ``.expected.json`` and ``.slots.json`` documents from a
    platform-neutral projection.

    Returns ``(expected_doc, slots_doc)``. The expected document's
    ``nodes`` field is a JSON object keyed by node id, in projection list
    order; the slots document is a JSON object mapping each ``slot:true``
    node id to its display text, in projection list order.

    Raises :class:`ProjectionValidationError` on any contract violation.
    """
    _validate_projection(projection)
    scale = float(projection["designPixelScale"])  # validated finite positive
    width = float(projection["artboardWidth"])

    expected_nodes: dict[str, Any] = {}
    slots: dict[str, Any] = {}
    for node in projection["nodes"]:
        expected_nodes[node["id"]] = _build_expected_node(node, scale)
        if node["slot"]:
            slots[node["id"]] = node["text"]

    expected_doc: dict[str, Any] = {
        "artboardWidth": projection["artboardWidth"],
        "artboardHeight": projection["artboardHeight"],
        "designPixelScale": projection["designPixelScale"],
        "logicalDesignWidth": width / scale,
        "nodes": expected_nodes,
    }
    return expected_doc, slots


def build_legacy_bytes(
    projection: Mapping[str, object],
) -> tuple[bytes, bytes]:
    """Build the legacy ``.expected.json`` and ``.slots.json`` byte payloads
    from a platform-neutral projection.

    The byte form is exactly::

        json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")

    with no sorted keys and no trailing newline.

    Raises :class:`ProjectionValidationError` on any contract violation.
    """
    expected_doc, slots_doc = build_documents(projection)
    expected_bytes = json.dumps(expected_doc, ensure_ascii=False, indent=2).encode("utf-8")
    slots_bytes = json.dumps(slots_doc, ensure_ascii=False, indent=2).encode("utf-8")
    return expected_bytes, slots_bytes


def build_projection_bytes(projection: Mapping[str, object]) -> bytes:
    """Build the canonical byte form of the platform-neutral projection.

    The projection is validated through the existing projection contract
    and then serialized as a detached strict-JSON document in the
    contract's fixed top-level key order (``kind``, ``schemaVersion``,
    ``artboardWidth``, ``artboardHeight``, ``designPixelScale``,
    ``nodes``) and fixed per-node key order, preserving the contractual
    node-list insertion order and nested JSON insertion order.

    The byte form is exactly::

        json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")

    with no sorted keys and no trailing newline.

    The function is deterministic for any custom :class:`Mapping` input
    that passes validation: caller-side ``Mapping`` subclasses are never
    serialized directly. Nested mutable values are detached via the
    strict-JSON clone so the returned bytes share no mutable nested
    container with the caller's projection; mutating the input after
    the call does not change the bytes a re-decode would yield.

    Raises :class:`ProjectionValidationError` on any contract violation
    (including NaN/infinity, bytes, tuples, sets, custom objects,
    non-string mapping keys, and cyclic containers anywhere in the
    projection).
    """
    _validate_projection(projection)
    # Detach the projection into a fresh strict-JSON tree preserving
    # the contractual key order at the top level and per-node, plus the
    # node-list insertion order and the nested JSON insertion order.
    # _strict_json_clone recursively rebuilds lists and dicts from the
    # input, so a custom Mapping subclass on the caller side is never
    # serialized directly.
    root_clone = _strict_json_clone(
        {
            key: projection[key]
            for key in _TOP_LEVEL_KEYS
        },
        "projection",
    )
    node_clones: list[Any] = []
    for index, node in enumerate(projection["nodes"]):
        # Re-key each node in the fixed contractual order. Nested
        # mutable values are detached via _strict_json_clone inside
        # _build_projection_node_clone.
        node_clone = _strict_json_clone(
            {key: node[key] for key in _NODE_KEYS},
            f"projection.nodes[{index}]",
        )
        node_clones.append(node_clone)
    root_clone["nodes"] = node_clones
    return json.dumps(root_clone, ensure_ascii=False, indent=2).encode("utf-8")
