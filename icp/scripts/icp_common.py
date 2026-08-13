#!/usr/bin/env python3
"""Small deterministic helpers shared by ICP P1a scripts.

This module is intentionally tiny: it owns the public error-code constants,
the strict JSON decoder (rejects duplicate keys / non-object roots), the
canonical-text encoder, a SHA-256 helper, and the versioned registry loader.
It never imports/execs/subprocesses registry values, and it never touches the
read-only ``iff`` skill.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Public error codes (exact strings are part of the P1a contract).
# ---------------------------------------------------------------------------

INVALID_INPUT = "invalid_input"
UNSUPPORTED_TASK_SOURCE = "unsupported_task_source"
UNSUPPORTED_TASK_FORMAT = "unsupported_task_format"
UNSUPPORTED_DESIGN_SOURCE = "unsupported_design_source"
UNSUPPORTED_PLATFORM = "unsupported_platform"
UNSUPPORTED_PROFILE = "unsupported_profile"
MISSING_MANDATORY_CAPABILITY = "missing_mandatory_capability"
TASK_PREFLIGHT_FAILED = "task_preflight_failed"
DESIGN_PREFLIGHT_FAILED = "design_preflight_failed"
PROJECT_PREFLIGHT_FAILED = "project_preflight_failed"
# P1b: a selection batch run root or manifest already exists and must never be
# overwritten or reused. Surfaced before any task row is mutated.
SELECTION_MANIFEST_CONFLICT = "selection_manifest_conflict"

ALL_ERROR_CODES = frozenset(
    {
        INVALID_INPUT,
        UNSUPPORTED_TASK_SOURCE,
        UNSUPPORTED_TASK_FORMAT,
        UNSUPPORTED_DESIGN_SOURCE,
        UNSUPPORTED_PLATFORM,
        UNSUPPORTED_PROFILE,
        MISSING_MANDATORY_CAPABILITY,
        TASK_PREFLIGHT_FAILED,
        DESIGN_PREFLIGHT_FAILED,
        PROJECT_PREFLIGHT_FAILED,
        SELECTION_MANIFEST_CONFLICT,
    }
)


# ---------------------------------------------------------------------------
# Typed config/preflight failures.
# ---------------------------------------------------------------------------


class ConfigError(ValueError):
    """A public, code-bearing failure raised during strict config resolution."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Strict JSON: reject duplicate keys and non-object roots up front.
# ---------------------------------------------------------------------------


class DuplicateKeyError(ValueError):
    """Raised by the strict object_pairs_hook when a JSON object repeats a key."""


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    for key, _value in pairs:
        if key in seen:
            raise DuplicateKeyError(f"duplicate JSON key: {key!r}")
        seen.add(key)
    return dict(pairs)


def decode_strict_config(raw: bytes) -> dict[str, Any]:
    """Decode a UTF-8 JSON config, rejecting malformed input up front.

    Returns the root object. Raises :class:`ConfigError` (code ``invalid_input``)
    for: non-UTF-8 bytes, JSON syntax errors, duplicate keys, or any root that
    is not a JSON object.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigError(INVALID_INPUT, f"config must be UTF-8 JSON: {exc}") from exc
    decoder = json.JSONDecoder(object_pairs_hook=reject_duplicate_keys)
    try:
        obj = decoder.decode(text)
    except DuplicateKeyError as exc:
        raise ConfigError(INVALID_INPUT, str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(INVALID_INPUT, f"config is not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise ConfigError(
            INVALID_INPUT,
            f"config root must be a JSON object, got {type(obj).__name__}",
        )
    return obj


# ---------------------------------------------------------------------------
# Canonical JSON encoding (deterministic for byte comparison).
# ---------------------------------------------------------------------------


def canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    """Encode ``payload`` deterministically (sorted keys, two-space indent)."""
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def failure_json(code: str, message: str) -> bytes:
    """Encode a public one-object failure payload for stderr emission."""
    return canonical_json_bytes({"ok": False, "code": code, "message": message})


# ---------------------------------------------------------------------------
# Digest helper.
# ---------------------------------------------------------------------------


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Versioned registry loader.
# ---------------------------------------------------------------------------

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "references" / "registries.json"


def load_registries() -> dict[str, Any]:
    """Load and lightly validate the versioned production registries.

    The registries live under ``icp/references/`` and have **no external
    override**: this function takes no parameters so callers cannot inject a
    different registry path. The data is decoded with the strict hook so
    duplicate keys surface as :class:`ConfigError`.
    """
    raw = REGISTRY_PATH.read_bytes()
    try:
        registries = json.loads(raw, object_pairs_hook=reject_duplicate_keys)
    except DuplicateKeyError as exc:
        raise ConfigError(INVALID_INPUT, f"registry has duplicate key: {exc}") from exc
    if not isinstance(registries, dict):
        raise ConfigError(INVALID_INPUT, "registry root must be a JSON object")
    return registries
