#!/usr/bin/env python3
"""ICP P2.5b Flutter fixture projection guard — v1.

This module is a Flutter compatibility-boundary primitive (NOT SharedCore)
that gates ``flutter.fixture_codegen.v1`` on the platform-neutral
expected/slots projection. It is the explicit first step of the fixture
operation, executed immediately before the existing frozen
``make_visual_fixture.py`` capsule consumer.

The guard is completely READ-ONLY: it never creates, writes, renames,
deletes, or symlinks any file; it never invokes a subprocess, socket,
URL, http client, shell, or dynamic import override; and it accepts no
caller-provided projection path or script override. SharedCore is loaded
ONLY from the fixed installed sibling path derived from ``__file__``.

For each (state_id, projection_file, slots_file) tuple passed on the
CLI, the guard:

  1. strict-decodes the projection file as UTF-8 JSON with duplicate-key
     rejection;
  2. requires ``build_projection_bytes(doc)`` to byte-for-byte equal the
     raw projection file bytes (canonical-projection check); and
  3. requires ``build_legacy_bytes(doc)[1]`` to byte-for-byte equal the
     raw slots file bytes (projection->slots byte equality).

On success the guard emits only a stable sanitized JSON summary carrying
``kind``, ``schema_version``, and ``states_verified`` (sorted list of
state ids). No paths or content are emitted.

On failure the guard returns a non-zero exit code and emits only the
exception type plus a fixed role/state-safe text to stderr; no
traceback, absolute path, raw file content, arbitrary exception text,
or environment is leaked.

CLI::

    python3 flutter_fixture_projection_guard_v1.py \\
        --run-root <absolute dir> \\
        --projection STATE=<absolute json> [--projection STATE=<absolute json> ...] \\
        --slots STATE=<absolute json> [--slots STATE=<absolute json> ...]

Exactly one ``--run-root`` is required. ``--projection`` may repeat 1..32
times; ``--slots`` may repeat 1..32 times. The two state-id sets must be
exactly equal and unique. Every state id must match
``^[a-z][a-z0-9_]*$``. Every input file must be an existing current-
owner non-symlink regular file strictly under ``run_root`` with no
symlinked ancestor; each file is bounded to 16 MiB.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

# Suppress bytecode emission so loading SharedCore never litters
# __pycache__ under shared_core/. This is defence-in-depth alongside the
# operation env's PYTHONDONTWRITEBYTECODE=1.
sys.dont_write_bytecode = True  # noqa: Q000

__all__ = ["FixtureProjectionGuardError", "main"]

# ---------------------------------------------------------------------------
# Fixed production paths derived from this module's installed location.
# Accepts NO override; this is the runtime surface.
# ---------------------------------------------------------------------------

_GUARD_DIR = Path(__file__).resolve().parent
_SHARED_CORE_DIR = _GUARD_DIR.parent / "shared_core"
_PROJECTION_MODULE_PATH = _SHARED_CORE_DIR / "expected_slots_projection_v1.py"

# Projection contract constants (must match SharedCore).
KIND = "icp.shared.expected-slots-projection.v1"
SCHEMA_VERSION = 1

# Bounded read maximum: 16 MiB per input file.
_MAX_FILE_BYTES = 16 * 1024 * 1024

# State id grammar (matches operations_v1._PACKAGE_RE and adapter's
# feature_id grammar).
_STATE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# Count limits (1..32 entries for --projection and --slots).
_MIN_ENTRIES = 1
_MAX_ENTRIES = 32


class FixtureProjectionGuardError(Exception):
    """A local Flutter fixture projection guard failure.

    Raised for any path/validation/canonical/slots-parity failure.
    Generic failures are converted at the public boundary (:func:`main`)
    to instances of this class whose message exposes only fixed
    role/state-safe text; arbitrary exception text, file contents, and
    tracebacks are never leaked.
    """


# ---------------------------------------------------------------------------
# SharedCore loader (fixed sibling path, no override).
# ---------------------------------------------------------------------------

_PROJECTION_MODULE: Any = None


def _load_projection_module():
    """Load SharedCore ``expected_slots_projection_v1`` by file path.

    The path is derived ONLY from this module's installed location. No
    caller override is accepted. Bytecode emission is suppressed via
    ``sys.dont_write_bytecode`` so no ``__pycache__`` appears under
    ``shared_core/``.
    """
    global _PROJECTION_MODULE
    if _PROJECTION_MODULE is None:
        _check_regular_nonsymlink(_PROJECTION_MODULE_PATH, "shared_core projection module")
        spec = importlib.util.spec_from_file_location(
            "p25b_shared_core_projection", str(_PROJECTION_MODULE_PATH)
        )
        if spec is None or spec.loader is None:
            raise FixtureProjectionGuardError("cannot load shared_core module spec")
        module = importlib.util.module_from_spec(spec)
        sys.modules["p25b_shared_core_projection"] = module
        spec.loader.exec_module(module)
        _PROJECTION_MODULE = module
    return _PROJECTION_MODULE


# ---------------------------------------------------------------------------
# Strict JSON decode with duplicate-key rejection.
# ---------------------------------------------------------------------------


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    for key, _value in pairs:
        if key in seen:
            raise FixtureProjectionGuardError("duplicate JSON key")
        seen.add(key)
    return dict(pairs)


def _decode_json_strict(raw: bytes, role: str) -> Any:
    """Decode ``raw`` as strict UTF-8 JSON with duplicate-key rejection.

    Raises :class:`FixtureProjectionGuardError` (type-only message) on
    any failure. The ``role`` is used only to disambiguate in the
    type-only error; no raw input is included in the message.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FixtureProjectionGuardError(
            f"{role}: not UTF-8: {type(exc).__name__}"
        ) from exc
    try:
        return json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except FixtureProjectionGuardError:
        raise
    except ValueError as exc:
        raise FixtureProjectionGuardError(f"{role}: not valid JSON") from exc


# ---------------------------------------------------------------------------
# Path / file validators (fail-closed, sanitized).
# ---------------------------------------------------------------------------


def _check_current_owner(st: os.stat_result, role: str) -> None:
    """Reject files not owned by the current effective user (Unix only).

    On platforms without ``os.geteuid`` this check is skipped (the spec
    allows non-owner rejection only "where portable").
    """
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None:
        return  # non-portable (e.g. Windows); skip
    try:
        if st.st_uid != geteuid():
            raise FixtureProjectionGuardError(f"{role}: not owned by current user")
    except AttributeError:
        return  # defensive: stat structure lacks st_uid


def _check_regular_nonsymlink(path: Path, role: str) -> None:
    """Require ``path`` to exist, be a regular file, and not be a symlink."""
    try:
        if path.is_symlink():
            raise FixtureProjectionGuardError(f"{role}: refusing symlink")
        st = path.lstat()
    except FileNotFoundError as exc:
        raise FixtureProjectionGuardError(f"{role}: not found") from exc
    except OSError as exc:
        raise FixtureProjectionGuardError(
            f"{role}: cannot lstat: {type(exc).__name__}"
        ) from exc
    if not stat.S_ISREG(st.st_mode):
        raise FixtureProjectionGuardError(f"{role}: not a regular file")


def _validate_abs_path(value: Any, role: str) -> Path:
    """Validate an absolute, lexically normalized path string."""
    if not isinstance(value, str):
        raise FixtureProjectionGuardError(
            f"{role}: must be a string, got {type(value).__name__}"
        )
    if not os.path.isabs(value):
        raise FixtureProjectionGuardError(f"{role}: not absolute")
    if any(part == ".." for part in Path(value).parts):
        raise FixtureProjectionGuardError(f"{role}: contains '..'")
    if os.path.normpath(value) != value:
        raise FixtureProjectionGuardError(f"{role}: not lexically normalized")
    if "\\" in value:
        raise FixtureProjectionGuardError(f"{role}: contains backslash")
    if "\x00" in value:
        raise FixtureProjectionGuardError(f"{role}: contains NUL")
    return Path(value)


def _validate_run_root(value: Any) -> Path:
    """Validate ``--run-root`` as an absolute lexically-normalized
    existing non-symlink real directory owned by the current user."""
    raw = _validate_abs_path(value, "run_root")
    try:
        if raw.is_symlink():
            raise FixtureProjectionGuardError("run_root: refusing symlink")
        st = raw.lstat()
    except FileNotFoundError as exc:
        raise FixtureProjectionGuardError("run_root: not found") from exc
    except OSError as exc:
        raise FixtureProjectionGuardError(
            f"run_root: cannot lstat: {type(exc).__name__}"
        ) from exc
    if not stat.S_ISDIR(st.st_mode):
        raise FixtureProjectionGuardError("run_root: not a directory")
    _check_current_owner(st, "run_root")
    # Strict-resolve identity check: rejects a symlinked ancestor under
    # run_root.
    try:
        resolved = raw.resolve(strict=True)
    except FileNotFoundError as exc:
        raise FixtureProjectionGuardError("run_root: resolve failed") from exc
    except OSError as exc:
        raise FixtureProjectionGuardError(
            f"run_root: resolve failed: {type(exc).__name__}"
        ) from exc
    if resolved != raw:
        raise FixtureProjectionGuardError(
            "run_root: supplied path differs from strict resolve"
        )
    return resolved


def _validate_input_file(path_str: str, run_root: Path, role: str) -> Path:
    """Validate a projection/slots input file as a non-symlink regular
    file strictly under ``run_root`` with no symlinked ancestor.

    Walks every component below ``run_root`` and requires each to be a
    non-symlink (ancestor) or non-symlink regular file (leaf). Strict-
    resolves the leaf and requires identity (no symlink escape). Owner
    is checked where portable.
    """
    raw = _validate_abs_path(path_str, role)
    # Containment: must be a strict descendant of run_root.
    try:
        rel = raw.relative_to(run_root)
    except ValueError as exc:
        raise FixtureProjectionGuardError(
            f"{role}: not contained in run_root"
        ) from exc
    if str(rel) == ".":
        raise FixtureProjectionGuardError(f"{role}: equals run_root")
    parts = rel.parts
    current = run_root
    last = len(parts) - 1
    for index, part in enumerate(parts):
        candidate = current / part
        try:
            if candidate.is_symlink():
                raise FixtureProjectionGuardError(
                    f"{role}: refusing symlinked component"
                )
            st = candidate.lstat()
        except FileNotFoundError as exc:
            raise FixtureProjectionGuardError(f"{role}: not found") from exc
        except OSError as exc:
            raise FixtureProjectionGuardError(
                f"{role}: cannot lstat: {type(exc).__name__}"
            ) from exc
        if index < last:
            if not stat.S_ISDIR(st.st_mode):
                raise FixtureProjectionGuardError(
                    f"{role}: ancestor not a directory"
                )
        else:
            if not stat.S_ISREG(st.st_mode):
                raise FixtureProjectionGuardError(
                    f"{role}: not a regular file"
                )
            _check_current_owner(st, role)
        current = candidate
    # Strict-resolve the leaf and require identity (no symlink escape).
    try:
        resolved = current.resolve(strict=True)
    except FileNotFoundError as exc:
        raise FixtureProjectionGuardError(f"{role}: resolve failed") from exc
    except OSError as exc:
        raise FixtureProjectionGuardError(
            f"{role}: resolve failed: {type(exc).__name__}"
        ) from exc
    if resolved != current:
        raise FixtureProjectionGuardError(f"{role}: path escape after resolve")
    return current


def _read_bounded(path: Path, role: str) -> bytes:
    """Read up to ``_MAX_FILE_BYTES + 1`` bytes from ``path``. Rejects
    files larger than the bound without reading them fully."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise FixtureProjectionGuardError(
            f"{role}: cannot stat: {type(exc).__name__}"
        ) from exc
    if size > _MAX_FILE_BYTES:
        raise FixtureProjectionGuardError(
            f"{role}: exceeds {_MAX_FILE_BYTES} bytes"
        )
    try:
        with open(str(path), "rb") as f:
            data = f.read()
    except OSError as exc:
        raise FixtureProjectionGuardError(
            f"{role}: cannot read: {type(exc).__name__}"
        ) from exc
    return data


# ---------------------------------------------------------------------------
# Arg parsing.
# ---------------------------------------------------------------------------


def _parse_pair(value: str, role: str) -> tuple[str, str]:
    """Parse a ``STATE=ABS_PATH`` pair into (state, abs_path)."""
    if "=" not in value:
        raise FixtureProjectionGuardError(
            f"{role}: not in STATE=ABS form"
        )
    state, abs_path = value.split("=", 1)
    if not state or not abs_path:
        raise FixtureProjectionGuardError(
            f"{role}: empty state or path"
        )
    if not _STATE_ID_RE.fullmatch(state):
        raise FixtureProjectionGuardError(
            f"{role}: state id invalid"
        )
    return state, abs_path


def _parse_args(argv: list[str]) -> tuple[Path, list[tuple[str, str]], list[tuple[str, str]]]:
    """Parse the EXACT CLI arguments. Raises SystemExit on any usage
    error, including an unknown flag.

    Returns ``(run_root, projection_pairs, slots_pairs)`` where each
    pairs list is the user-supplied order (state validation happens
    after parsing).
    """
    ap = argparse.ArgumentParser(
        prog="flutter_fixture_projection_guard_v1.py",
        description=(
            "P2.5b Flutter fixture projection guard: a read-only "
            "compatility-boundary primitive that gates the fixture "
            "operation on the platform-neutral expected/slots projection."
        ),
        add_help=True,
    )
    ap.add_argument("--run-root", dest="run_root", required=True)
    ap.add_argument(
        "--projection", dest="projection", action="append",
        default=None, metavar="STATE=<absolute json>",
    )
    ap.add_argument(
        "--slots", dest="slots", action="append",
        default=None, metavar="STATE=<absolute json>",
    )
    parsed = ap.parse_args(argv)
    if parsed.projection is None or len(parsed.projection) < _MIN_ENTRIES:
        ap.error(
            f"--projection must appear at least {_MIN_ENTRIES} time(s)"
        )
    if parsed.slots is None or len(parsed.slots) < _MIN_ENTRIES:
        ap.error(
            f"--slots must appear at least {_MIN_ENTRIES} time(s)"
        )
    if len(parsed.projection) > _MAX_ENTRIES:
        ap.error(
            f"--projection appears too many times "
            f"({len(parsed.projection)} > {_MAX_ENTRIES})"
        )
    if len(parsed.slots) > _MAX_ENTRIES:
        ap.error(
            f"--slots appears too many times "
            f"({len(parsed.slots)} > {_MAX_ENTRIES})"
        )
    return parsed.run_root, parsed.projection, parsed.slots


# ---------------------------------------------------------------------------
# Core run.
# ---------------------------------------------------------------------------


def _run(
    run_root: Path,
    projection_pairs: list[str],
    slots_pairs: list[str],
) -> dict[str, Any]:
    """For each (state, projection, slots) tuple, verify the canonical
    projection check and the projection->slots byte equality.

    Returns a stable sanitized summary (no paths/content).
    """
    # Parse pairs into (state, abs_path_str) and require unique states.
    projection_map: dict[str, str] = {}
    for raw in projection_pairs:
        state, abs_path = _parse_pair(raw, "projection")
        if state in projection_map:
            raise FixtureProjectionGuardError(
                "projection: duplicate state id"
            )
        projection_map[state] = abs_path
    slots_map: dict[str, str] = {}
    for raw in slots_pairs:
        state, abs_path = _parse_pair(raw, "slots")
        if state in slots_map:
            raise FixtureProjectionGuardError(
                "slots: duplicate state id"
            )
        slots_map[state] = abs_path
    # The two state-id sets must be exactly equal.
    if set(projection_map.keys()) != set(slots_map.keys()):
        raise FixtureProjectionGuardError(
            "projection/slots state sets differ"
        )

    # Validate every input file (path/symlink/owner/containment).
    states_sorted = sorted(projection_map.keys())
    state_inputs: list[tuple[str, Path, Path]] = []
    for state in states_sorted:
        projection_path = _validate_input_file(
            projection_map[state], run_root, f"projection[{state}]"
        )
        slots_path = _validate_input_file(
            slots_map[state], run_root, f"slots[{state}]"
        )
        state_inputs.append((state, projection_path, slots_path))

    # Load SharedCore for the canonical-projection and projection->slots
    # checks.
    projection_module = _load_projection_module()

    # Verify each (state, projection, slots) tuple.
    for state, projection_path, slots_path in state_inputs:
        # Bounded-read both files.
        raw_projection_bytes = _read_bounded(projection_path, f"projection[{state}]")
        raw_slots_bytes = _read_bounded(slots_path, f"slots[{state}]")
        # Strict UTF-8 JSON decode with duplicate-key rejection.
        try:
            doc = _decode_json_strict(raw_projection_bytes, f"projection[{state}]")
        except FixtureProjectionGuardError:
            raise
        # Canonical-projection check: build_projection_bytes(doc) must
        # equal the raw projection bytes byte-for-byte.
        try:
            rebuilt_projection_bytes = projection_module.build_projection_bytes(doc)
        except projection_module.ProjectionValidationError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise FixtureProjectionGuardError(
                f"projection[{state}]: shared_core build_projection_bytes "
                f"raised {type(exc).__name__}"
            ) from exc
        if rebuilt_projection_bytes != raw_projection_bytes:
            raise FixtureProjectionGuardError(
                f"projection[{state}]: canonical bytes mismatch"
            )
        # projection->slots byte equality: build_legacy_bytes(doc)[1]
        # must equal the raw slots bytes byte-for-byte.
        try:
            _expected_bytes, rebuilt_slots_bytes = (
                projection_module.build_legacy_bytes(doc)
            )
        except projection_module.ProjectionValidationError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise FixtureProjectionGuardError(
                f"projection[{state}]: shared_core build_legacy_bytes "
                f"raised {type(exc).__name__}"
            ) from exc
        if rebuilt_slots_bytes != raw_slots_bytes:
            raise FixtureProjectionGuardError(
                f"projection[{state}]: slots bytes mismatch"
            )

    # Sanitized summary (no paths/content).
    return {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "states_verified": states_sorted,
    }


# ---------------------------------------------------------------------------
# CLI / public main().
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Parses ``--run-root``, ``--projection STATE=<abs json>`` (repeated),
    and ``--slots STATE=<abs json>`` (repeated), runs the read-only
    guard, and prints a stable sanitized JSON summary to stdout on
    success. On any failure, prints the type name plus fixed role/state-
    safe text to stderr (no traceback, no raw input/path/file-content
    leak, no environment) and returns a non-zero exit code.
    """
    if argv is None:
        argv = sys.argv[1:]
    try:
        run_root_str, projection_pairs, slots_pairs = _parse_args(list(argv))
    except SystemExit as exc:
        # argparse already printed a sanitized usage message.
        return int(exc.code) if isinstance(exc.code, int) else 2

    try:
        run_root = _validate_run_root(run_root_str)
        summary = _run(run_root, projection_pairs, slots_pairs)
    except FixtureProjectionGuardError as exc:
        # Type-only message; no traceback, no raw input/path leak.
        sys.stderr.write(f"FixtureProjectionGuardError: {exc}\n")
        return 1
    except Exception as exc:  # noqa: BLE001
        # Convert any unexpected exception to a type-only message.
        sys.stderr.write(
            f"FixtureProjectionGuardError: unexpected {type(exc).__name__}\n"
        )
        return 1

    sys.stdout.write(json.dumps(summary, ensure_ascii=False, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
