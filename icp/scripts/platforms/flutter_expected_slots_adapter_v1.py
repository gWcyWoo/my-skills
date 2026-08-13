#!/usr/bin/env python3
"""ICP P2.5a2/P2.5b Flutter expected/slots adapter — v1.

This module is the explicit, digest-bound post-step that runs immediately
after the frozen iFF v1 ``generate_canvas.py`` in the
``flutter.visible_codegen.v1`` operation. It is a fixed project-local
platform primitive: it is never copied into or registered inside the
frozen vendor capsule.

The adapter:

  1. reads ONLY the exact ``<canvas>.expected.json`` and
     ``<canvas>.slots.json`` sidecars emitted by the immediately
     preceding ``generate_canvas`` step (bounded 16 MiB, strict UTF-8,
     strict JSON with duplicate-key rejection);
  2. reconstructs the platform-neutral
     ``icp.shared.expected-slots-projection.v1`` losslessly from those
     sidecars (preserving node insertion order, mapping slot booleans
     from the slots sidecar's id set, and ignoring the derived
     ``logicalBbox`` / ``logicalDesignWidth`` fields);
  3. loads SharedCore (``shared_core/expected_slots_projection_v1``)
     ONLY from the fixed installed sibling path and calls
     ``build_legacy_bytes(projection)`` to rebuild both sidecar bytes;
  4. requires byte-for-byte equality between both rebuilt sidecars and
     the original raw bytes (a failure in either prevents the first
     replace); and
  5. only then atomically persists the byte-identical SharedCore output
     as the final expected/slots truth: prepare + fsync both temp files,
     revalidate both source identities, then replace each original
     regular file (preserving its mode, rejecting symlinks and
     non-current-owner files).

P2.5b extends the same adapter with an optional projection-publish
mode. When the trusted operation passes the optional pair
``--run-root <abs dir>`` and ``--feature-id <id>`` (which must appear
together or both be absent), the adapter additionally:

  * validates ``run_root`` as an absolute normalized existing current-
    owner non-symlink directory disjoint from ``project_root`` under
    the existing root-boundary policy;
  * validates ``feature_id`` against ``^[a-z][a-z0-9_]*$``;
  * derives the canonical SharedCore projection bytes via
    ``build_projection_bytes(projection)`` (the same validated
    projection from step 2 above);
  * publishes those bytes exactly once to the fixed derived artifact
    path ``<run_root>/expected_slots_projections/<feature_id>.json``
    (max 16 MiB) using an atomic create-if-absent strategy with a
    current-owner, mode-0600, fsynced temp in the target directory and
    a directory fsync. Pre-existing output (file, dir, or symlink) fails
    closed and is never overwritten.

The projection-output preconditions and canonical bytes are fully
validated BEFORE the first legacy-sidecar replace. If final publication
fails after the legacy sidecars were replaced, those sidecars remain
semantically unchanged because their old/new bytes are identical; the
adapter reports failure and never fabricates success.

Fail-closed boundaries:

* Missing, malformed, noncanonical (e.g. trailing newline), duplicate-
  key, oversized (>16 MiB), symlinked, out-of-root, changed-during-read,
  or parity-divergent inputs raise :class:`ExpectedSlotsAdapterError`
  and write nothing.
* Failures expose only the type name (no traceback, no raw input/path
  leak, no file contents).
* The module is standard-library-only. It never imports ``subprocess``,
  ``socket``, ``urllib``, ``http.client``, the frozen capsule, or any
  platform/operations module. It never accepts a caller-provided script
  root, projection path, output path, or projection-bytes override.
* SharedCore is loaded only from the fixed installed sibling path
  (``Path(__file__).resolve().parent.parent / "shared_core" /
  "expected_slots_projection_v1.py"``); bytecode emission is suppressed.

CLI::

    python3 flutter_expected_slots_adapter_v1.py \\
        --project-root <absolute dir> \\
        --canvas <absolute .dart path> \\
        [--run-root <absolute dir> --feature-id <id>]

The sidecar paths are derived exactly as ``<canvas>.expected.json`` and
``<canvas>.slots.json``. ``--canvas`` must be a strict descendant of
``--project-root``. ``--run-root`` and ``--feature-id`` must appear
together or both be absent (compatibility mode).

In projection mode the adapter's stdout summary carries the existing
stable summary fields plus only a stable run-relative projection
artifact path (``expected_slots_projections/<feature_id>.json``); it
never emits the absolute supplied run root or raw projection content.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

# Suppress bytecode emission so loading SharedCore never litters
# __pycache__ under shared_core/. This is defence-in-depth alongside the
# operation env's PYTHONDONTWRITEBYTECODE=1.
sys.dont_write_bytecode = True  # noqa: Q000

__all__ = ["ExpectedSlotsAdapterError", "main"]

# ---------------------------------------------------------------------------
# Fixed production paths derived from this module's installed location.
# Accepts NO override; this is the runtime surface.
# ---------------------------------------------------------------------------

_ADAPTER_DIR = Path(__file__).resolve().parent
_SHARED_CORE_DIR = _ADAPTER_DIR.parent / "shared_core"
_PROJECTION_MODULE_PATH = _SHARED_CORE_DIR / "expected_slots_projection_v1.py"

# Projection contract constants (must match SharedCore).
KIND = "icp.shared.expected-slots-projection.v1"
SCHEMA_VERSION = 1

# Bounded read maximum: 16 MiB per sidecar.
_MAX_SIDECAR_BYTES = 16 * 1024 * 1024

# P2.5b: maximum canonical projection bytes the adapter will publish
# (matches the sidecar bound; the projection artifact must not exceed it).
_MAX_PROJECTION_BYTES = _MAX_SIDECAR_BYTES

# P2.5b: ``feature_id`` grammar (matches operations_v1._PACKAGE_RE and
# the slot state-id grammar).
_FEATURE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# P2.5b: fixed derived projection artifact directory under run_root.
_PROJECTION_DIR_NAME = "expected_slots_projections"

# P2.5b: fixed artifact mode (current-owner read/write only).
_PROJECTION_ARTIFACT_MODE = 0o600

# Exact top-level keys of the frozen expected.json sidecar.
_EXPECTED_TOP_KEYS = frozenset(
    {
        "artboardWidth",
        "artboardHeight",
        "designPixelScale",
        "logicalDesignWidth",
        "nodes",
    }
)

# Exact per-node keys of the frozen expected.json sidecar.
_EXPECTED_NODE_KEYS = frozenset(
    {
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
    }
)

# Narrow test seam: an optional callable invoked right before source
# identity revalidation (after both temp files are prepared+fsynced, before
# any replace). Tests use this to simulate a source-identity change between
# read and replace. Production leaves this ``None``.
_TEST_PRE_REPLACE_HOOK: Callable[[], None] | None = None

# Narrow test seam: an optional callable invoked immediately AFTER each
# bounded read completes (and BEFORE the post-read lstat revalidation).
# Tests use this to simulate a same-bytes/different-inode substitution
# during the read window. The callable receives the sidecar ``role``
# string ("expected" or "slots"). Production leaves this ``None``.
_TEST_POST_READ_HOOK: Callable[[str], None] | None = None


class ExpectedSlotsAdapterError(Exception):
    """A local Flutter expected/slots adapter failure.

    Raised for any path/validation/parity/IO failure. Generic failures are
    converted at the public boundary (:func:`main`) to instances of this
    class whose message exposes only the original exception's type name;
    arbitrary exception text, file contents, and tracebacks are never
    leaked.
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
            "p25a2_shared_core_projection", str(_PROJECTION_MODULE_PATH)
        )
        if spec is None or spec.loader is None:
            raise ExpectedSlotsAdapterError("cannot load shared_core module spec")
        module = importlib.util.module_from_spec(spec)
        sys.modules["p25a2_shared_core_projection"] = module
        spec.loader.exec_module(module)
        _PROJECTION_MODULE = module
    return _PROJECTION_MODULE


# ---------------------------------------------------------------------------
# Canonical JSON / digest helpers.
# ---------------------------------------------------------------------------


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    for key, _value in pairs:
        if key in seen:
            raise ExpectedSlotsAdapterError("duplicate JSON key")
        seen.add(key)
    return dict(pairs)


def _decode_json_strict(raw: bytes, role: str) -> Any:
    """Decode ``raw`` as strict UTF-8 JSON with duplicate-key rejection.

    Raises :class:`ExpectedSlotsAdapterError` (type-only message) on any
    failure. The ``role`` is used only to disambiguate in the type-only
    error; no raw input is included in the message.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ExpectedSlotsAdapterError(
            f"{role}: not UTF-8: {type(exc).__name__}"
        ) from exc
    try:
        return json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except ExpectedSlotsAdapterError:
        raise
    except ValueError as exc:
        raise ExpectedSlotsAdapterError(f"{role}: not valid JSON") from exc


# ---------------------------------------------------------------------------
# Path / file validators (fail-closed, sanitized).
# ---------------------------------------------------------------------------


def _check_regular_nonsymlink(path: Path, role: str) -> None:
    """Require ``path`` to exist, be a regular file, and not be a symlink."""
    try:
        if path.is_symlink():
            raise ExpectedSlotsAdapterError(f"{role}: refusing symlink")
        st = path.lstat()
    except FileNotFoundError as exc:
        raise ExpectedSlotsAdapterError(f"{role}: not found") from exc
    except OSError as exc:
        raise ExpectedSlotsAdapterError(
            f"{role}: cannot lstat: {type(exc).__name__}"
        ) from exc
    if not stat.S_ISREG(st.st_mode):
        raise ExpectedSlotsAdapterError(f"{role}: not a regular file")


def _check_dir_nonsymlink(path: Path, role: str) -> None:
    try:
        if path.is_symlink():
            raise ExpectedSlotsAdapterError(f"{role}: refusing symlink")
        st = path.lstat()
    except FileNotFoundError as exc:
        raise ExpectedSlotsAdapterError(f"{role}: not found") from exc
    except OSError as exc:
        raise ExpectedSlotsAdapterError(
            f"{role}: cannot lstat: {type(exc).__name__}"
        ) from exc
    if not stat.S_ISDIR(st.st_mode):
        raise ExpectedSlotsAdapterError(f"{role}: not a directory")


def _check_current_owner(path: Path, st: os.stat_result, role: str) -> None:
    """Reject files not owned by the current effective user (Unix only).

    On platforms without ``os.geteuid`` this check is skipped (the spec
    allows non-owner rejection only "where portable").
    """
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None:
        return  # non-portable (e.g. Windows); skip
    try:
        if st.st_uid != geteuid():
            raise ExpectedSlotsAdapterError(f"{role}: not owned by current user")
    except AttributeError:
        return  # defensive: stat structure lacks st_uid


def _lstat_identity(path: Path, role: str) -> os.stat_result:
    """Capture the lstat identity of a regular non-symlink file owned by
    the current user. Returns the ``os.stat_result`` so callers can
    compare ``(st_dev, st_ino, st_size, st_mtime_ns, st_mode, st_uid)``
    tuples for exact identity equality.
    """
    try:
        if path.is_symlink():
            raise ExpectedSlotsAdapterError(f"{role}: refusing symlink")
        st = path.lstat()
    except FileNotFoundError as exc:
        raise ExpectedSlotsAdapterError(f"{role}: not found") from exc
    except OSError as exc:
        raise ExpectedSlotsAdapterError(
            f"{role}: cannot lstat: {type(exc).__name__}"
        ) from exc
    if not stat.S_ISREG(st.st_mode):
        raise ExpectedSlotsAdapterError(f"{role}: not a regular file")
    _check_current_owner(path, st, role)
    return st


def _identity_tuple(st: os.stat_result) -> tuple[Any, ...]:
    """Return the canonical identity tuple for an ``os.stat_result``.

    Uses ``(st_dev, st_ino, st_size, st_mtime_ns, st_mode, st_uid)``.
    On platforms lacking one of these attributes the field is replaced
    with ``None`` so the comparison remains well-defined; this never
    weakens the check on the supported POSIX/Darwin targets because all
    six fields are always present there.
    """
    return (
        getattr(st, "st_dev", None),
        getattr(st, "st_ino", None),
        getattr(st, "st_size", None),
        getattr(st, "st_mtime_ns", None),
        getattr(st, "st_mode", None),
        getattr(st, "st_uid", None),
    )


def _validate_abs_path(value: Any, role: str) -> Path:
    """Validate an absolute, lexically normalized path string."""
    if not isinstance(value, str):
        raise ExpectedSlotsAdapterError(
            f"{role}: must be a string, got {type(value).__name__}"
        )
    if not os.path.isabs(value):
        raise ExpectedSlotsAdapterError(f"{role}: not absolute")
    if any(part == ".." for part in Path(value).parts):
        raise ExpectedSlotsAdapterError(f"{role}: contains '..'")
    if os.path.normpath(value) != value:
        raise ExpectedSlotsAdapterError(f"{role}: not lexically normalized")
    return Path(value)


def _validate_project_root(value: Any) -> Path:
    """Validate the ``--project-root`` absolute non-symlink real directory."""
    raw = _validate_abs_path(value, "project_root")
    try:
        resolved = raw.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ExpectedSlotsAdapterError("project_root: does not exist") from exc
    except OSError as exc:
        raise ExpectedSlotsAdapterError(
            f"project_root: resolve failed: {type(exc).__name__}"
        ) from exc
    if resolved != raw:
        raise ExpectedSlotsAdapterError(
            "project_root: supplied path differs from strict resolve"
        )
    _check_dir_nonsymlink(resolved, "project_root")
    return resolved


def _validate_canvas(value: Any, project_root: Path) -> Path:
    """Validate the ``--canvas`` absolute non-symlink regular .dart file
    strictly inside ``project_root``.

    Walks every ancestor component below ``project_root`` and requires each
    to be a non-symlink directory (the leaf must be a non-symlink regular
    file). Strict-resolves the leaf and requires it to equal the lexical
    path (no symlink escape). Rejects files not owned by the current user
    where portable.
    """
    raw = _validate_abs_path(value, "canvas")
    if not value.endswith(".dart"):  # type: ignore[union-attr]
        raise ExpectedSlotsAdapterError("canvas: must end with .dart")
    # Containment: canvas must be a strict descendant of project_root.
    try:
        rel = raw.relative_to(project_root)
    except ValueError as exc:
        raise ExpectedSlotsAdapterError(
            "canvas: not contained in project_root"
        ) from exc
    if str(rel) == ".":
        raise ExpectedSlotsAdapterError("canvas: equals project_root")
    # Walk each component below project_root; require non-symlink dirs for
    # ancestors and non-symlink regular for the leaf.
    current = project_root
    parts = rel.parts
    last = len(parts) - 1
    for index, part in enumerate(parts):
        candidate = current / part
        try:
            if candidate.is_symlink():
                raise ExpectedSlotsAdapterError(
                    "canvas: refusing symlinked component"
                )
            st = candidate.lstat()
        except FileNotFoundError as exc:
            raise ExpectedSlotsAdapterError("canvas: not found") from exc
        except OSError as exc:
            raise ExpectedSlotsAdapterError(
                f"canvas: cannot lstat: {type(exc).__name__}"
            ) from exc
        if index < last:
            if not stat.S_ISDIR(st.st_mode):
                raise ExpectedSlotsAdapterError(
                    "canvas: ancestor not a directory"
                )
        else:
            if not stat.S_ISREG(st.st_mode):
                raise ExpectedSlotsAdapterError("canvas: not a regular file")
            _check_current_owner(candidate, st, "canvas")
        current = candidate
    # Strict-resolve the leaf and require identity (no symlink escape).
    try:
        resolved = current.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ExpectedSlotsAdapterError("canvas: resolve failed") from exc
    except OSError as exc:
        raise ExpectedSlotsAdapterError(
            f"canvas: resolve failed: {type(exc).__name__}"
        ) from exc
    if resolved != current:
        raise ExpectedSlotsAdapterError("canvas: path escape after resolve")
    return current


# ---------------------------------------------------------------------------
# P2.5b: --run-root / --feature-id validation + projection artifact
# publication. The projection artifact is the canonical SharedCore
# projection bytes for the sidecar-reconstructed projection, published
# once to a fixed derived path under run_root.
# ---------------------------------------------------------------------------


def _validate_run_root(value: Any, project_root: Path) -> Path:
    """Validate ``--run-root`` as an absolute lexically-normalized
    existing non-symlink real directory owned by the current user and
    disjoint from ``project_root`` under the existing root-boundary
    policy.

    The accepted shapes mirror the operations_v1 root-boundary policy:
      * ``run_root`` disjoint from ``project_root`` (project-external
        layout); or
      * ``run_root`` nested inside ``project_root`` ONLY when its
        project-relative path is exactly ``.iff/icp_runs/<batch_id>``
        (the frozen Flutter manifest's canonical internal run root).

    Rejected: equality, project_root nested inside run_root, any other
    project-internal path, symlinks (root or any ancestor), non-directory,
    missing, non-current-owner, lexical non-normalization, ``..``
    components. No caller-provided output path or projection-bytes
    override is accepted.
    """
    raw = _validate_abs_path(value, "run_root")
    try:
        resolved = raw.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ExpectedSlotsAdapterError("run_root: does not exist") from exc
    except OSError as exc:
        raise ExpectedSlotsAdapterError(
            f"run_root: resolve failed: {type(exc).__name__}"
        ) from exc
    if resolved != raw:
        raise ExpectedSlotsAdapterError(
            "run_root: supplied path differs from strict resolve"
        )
    _check_dir_nonsymlink(resolved, "run_root")
    # Owner check (where portable).
    try:
        st = resolved.lstat()
    except OSError as exc:
        raise ExpectedSlotsAdapterError(
            f"run_root: cannot lstat: {type(exc).__name__}"
        ) from exc
    _check_current_owner(resolved, st, "run_root")
    # Boundary: equality and project-inside-run are always rejected.
    if resolved == project_root:
        raise ExpectedSlotsAdapterError(
            "run_root: must differ from project_root"
        )
    try:
        project_root.relative_to(resolved)
        # project_root is at or under run_root: reject.
        raise ExpectedSlotsAdapterError(
            "run_root: must not contain project_root"
        )
    except ValueError:
        pass
    try:
        rel = resolved.relative_to(project_root)
    except ValueError:
        # Disjoint: accepted (project-external layout).
        return resolved
    # run_root is strictly inside project_root. Require the exact
    # ``.iff/icp_runs/<batch_id>`` internal manifest path. The batch
    # grammar matches the freezer's safe batch id rule
    # (``^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$``).
    parts = rel.parts
    if (
        len(parts) == 3
        and parts[0] == ".iff"
        and parts[1] == "icp_runs"
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", parts[2])
    ):
        return resolved
    raise ExpectedSlotsAdapterError(
        "run_root: nested run_root must be the exact frozen manifest "
        "path .iff/icp_runs/<batch_id>"
    )


def _validate_feature_id(value: Any) -> str:
    if not isinstance(value, str):
        raise ExpectedSlotsAdapterError(
            f"feature_id: must be a string, got {type(value).__name__}"
        )
    if not _FEATURE_ID_RE.fullmatch(value):
        raise ExpectedSlotsAdapterError(
            "feature_id: must match ^[a-z][a-z0-9_]*$"
        )
    return value


def _validate_run_root_ancestor_nonsymlink(run_root: Path) -> None:
    """Walk every ancestor of ``run_root`` up to (but not including) the
    filesystem root and require each to be a non-symlink directory.
    Defence-in-depth against a symlinked ancestor that strict-resolve
    did not surface (on platforms where resolve() follows symlinks but
    the lexical chain contains a symlink)."""
    # Start from run_root.parent; run_root itself is already validated
    # non-symlink by _validate_run_root.
    current = run_root.parent
    seen = set()
    while current != current.parent:
        if current in seen:
            break  # defensive against a pathological loop
        seen.add(current)
        try:
            if current.is_symlink():
                raise ExpectedSlotsAdapterError(
                    "run_root: refusing symlinked ancestor"
                )
        except OSError as exc:
            raise ExpectedSlotsAdapterError(
                f"run_root: ancestor lstat failed: {type(exc).__name__}"
            ) from exc
        current = current.parent


def _fsync_dir(path: Path) -> None:
    """fsync a directory path (best-effort; required for atomicity)."""
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError as exc:
        raise ExpectedSlotsAdapterError(
            f"projection_artifact: cannot open dir for fsync: "
            f"{type(exc).__name__}"
        ) from exc
    try:
        os.fsync(fd)
    except OSError as exc:
        raise ExpectedSlotsAdapterError(
            f"projection_artifact: cannot fsync dir: {type(exc).__name__}"
        ) from exc
    finally:
        os.close(fd)


def _publish_projection_artifact(
    run_root: Path, feature_id: str, projection_bytes: bytes
) -> str:
    """Atomically publish ``projection_bytes`` exactly once to the fixed
    derived artifact path
    ``<run_root>/expected_slots_projections/<feature_id>.json``.

    Requirements:
      * Maximum artifact size: 16 MiB.
      * The artifact directory is created if absent (the directory
        itself is fsynced).
      * Pre-existing output (file, directory, or symlink) at the
        artifact path fails closed and is never overwritten.
      * Atomic create-if-absent publication from a current-owner,
        mode-0600, fsynced temp in the target directory using a
        same-filesystem hard-link create-if-absent strategy, then a
        directory fsync.
      * Temp files are cleaned up on every failure path.
      * Returns the run-relative artifact POSIX path
        (``expected_slots_projections/<feature_id>.json``).
    """
    if len(projection_bytes) > _MAX_PROJECTION_BYTES:
        raise ExpectedSlotsAdapterError(
            "projection_artifact: exceeds {_MAX_PROJECTION_BYTES} bytes".format(
                _MAX_PROJECTION_BYTES=_MAX_PROJECTION_BYTES
            )
        )
    # Validate run_root's ancestor chain (no symlinked ancestor).
    _validate_run_root_ancestor_nonsymlink(run_root)
    artifact_dir = run_root / _PROJECTION_DIR_NAME
    artifact_path = artifact_dir / f"{feature_id}.json"
    rel_path = f"{_PROJECTION_DIR_NAME}/{feature_id}.json"
    # Create the artifact directory if absent (mkdir is allowed here;
    # this is the publish step, not the read path). Reject if a regular
    # file or symlink already exists at the directory path.
    try:
        if artifact_dir.is_symlink():
            raise ExpectedSlotsAdapterError(
                "projection_artifact: refusing symlinked directory"
            )
    except OSError as exc:
        raise ExpectedSlotsAdapterError(
            f"projection_artifact: cannot lstat dir: {type(exc).__name__}"
        ) from exc
    if not artifact_dir.exists():
        try:
            artifact_dir.mkdir(mode=0o700)
        except FileExistsError:
            # Lost a race with a concurrent creator; that's fine.
            pass
        except OSError as exc:
            raise ExpectedSlotsAdapterError(
                f"projection_artifact: cannot mkdir: {type(exc).__name__}"
            ) from exc
    # Re-lstat the directory post-mkdir.
    try:
        dir_st = artifact_dir.lstat()
    except OSError as exc:
        raise ExpectedSlotsAdapterError(
            f"projection_artifact: cannot stat dir: {type(exc).__name__}"
        ) from exc
    if not stat.S_ISDIR(dir_st.st_mode):
        raise ExpectedSlotsAdapterError(
            "projection_artifact: directory path occupied by non-directory"
        )
    _check_current_owner(artifact_dir, dir_st, "projection_artifact dir")
    # Publish-once: any existing entry at artifact_path fails closed.
    # We do NOT follow a symlink leaf, and we do NOT overwrite a file,
    # directory, or symlink.
    try:
        exists_lstat = artifact_path.lstat()
    except FileNotFoundError:
        exists_lstat = None
    except OSError as exc:
        raise ExpectedSlotsAdapterError(
            f"projection_artifact: cannot lstat: {type(exc).__name__}"
        ) from exc
    if exists_lstat is not None:
        # Fail closed regardless of type (file/dir/symlink/etc).
        raise ExpectedSlotsAdapterError(
            "projection_artifact: exists, refusing overwrite"
        )
    # Prepare a current-owner, mode-0600, fsynced temp in the target
    # directory.
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=str(artifact_dir),
            prefix=".p25b_",
            suffix=".tmp",
            delete=False,
        ) as tf:
            tf.write(projection_bytes)
            tf.flush()
            os.fsync(tf.fileno())
        temp_path = Path(tf.name)
        # Apply mode 0600 to the temp.
        try:
            os.chmod(temp_path, _PROJECTION_ARTIFACT_MODE)
        except OSError as exc:
            raise ExpectedSlotsAdapterError(
                f"projection_artifact: cannot chmod temp: "
                f"{type(exc).__name__}"
            ) from exc
        # Owner-check the temp.
        try:
            temp_st = temp_path.lstat()
        except OSError as exc:
            raise ExpectedSlotsAdapterError(
                f"projection_artifact: cannot stat temp: "
                f"{type(exc).__name__}"
            ) from exc
        if not stat.S_ISREG(temp_st.st_mode):
            raise ExpectedSlotsAdapterError(
                "projection_artifact: temp not a regular file"
            )
        _check_current_owner(temp_path, temp_st, "projection_artifact temp")
        # Re-verify the target still does not exist (no race-window
        # creation by a third party we would clobber). Atomic
        # create-if-absent via hard-link publication: ``os.link`` fails
        # with FileExistsError if the target already exists, so it is a
        # true create-if-absent (no overwrite even on a race).
        try:
            os.link(temp_path, artifact_path)
        except FileExistsError as exc:
            raise ExpectedSlotsAdapterError(
                "projection_artifact: exists, refusing overwrite"
            ) from exc
        except OSError as exc:
            raise ExpectedSlotsAdapterError(
                f"projection_artifact: link failed: {type(exc).__name__}"
            ) from exc
        # fsync the directory so the new directory entry is durable.
        _fsync_dir(artifact_dir)
        # Verify the published artifact (post-link sanity).
        try:
            pub_st = artifact_path.lstat()
        except OSError as exc:
            raise ExpectedSlotsAdapterError(
                f"projection_artifact: cannot stat published: "
                f"{type(exc).__name__}"
            ) from exc
        if not stat.S_ISREG(pub_st.st_mode):
            raise ExpectedSlotsAdapterError(
                "projection_artifact: published not a regular file"
            )
        if stat.S_IMODE(pub_st.st_mode) != _PROJECTION_ARTIFACT_MODE:
            raise ExpectedSlotsAdapterError(
                "projection_artifact: published mode drift"
            )
        _check_current_owner(artifact_path, pub_st, "projection_artifact published")
        # Unlink the temp (the hard link created a separate directory
        # entry, so the temp's inode is still referenced by the artifact).
        try:
            temp_path.unlink()
        except OSError:
            # Best-effort cleanup; the publication itself succeeded.
            pass
        temp_path = None
        return rel_path
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Bounded read (16 MiB maximum per sidecar).
# ---------------------------------------------------------------------------


def _read_bounded(path: Path, role: str) -> bytes:
    """Read up to ``_MAX_SIDECAR_BYTES + 1`` bytes from ``path``. Rejects
    files larger than the bound without reading them fully."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ExpectedSlotsAdapterError(
            f"{role}: cannot stat: {type(exc).__name__}"
        ) from exc
    if size > _MAX_SIDECAR_BYTES:
        raise ExpectedSlotsAdapterError(
            f"{role}: exceeds {_MAX_SIDECAR_BYTES} bytes"
        )
    try:
        with open(str(path), "rb") as f:
            data = f.read()
    except OSError as exc:
        raise ExpectedSlotsAdapterError(
            f"{role}: cannot read: {type(exc).__name__}"
        ) from exc
    return data


def _read_with_identity_check(
    path: Path, role: str
) -> tuple[bytes, os.stat_result]:
    """Bounded-read ``path`` and capture its identity across the read
    window, returning ``(data, post_read_stat)``.

    The identity window is:

      1. capture lstat identity BEFORE the bounded read;
      2. bounded-read the file;
      3. fire the optional post-read test seam (so tests can simulate a
         same-bytes/different-inode substitution during the read window);
      4. immediately lstat again and require exact equality of
         ``(st_dev, st_ino, st_size, st_mtime_ns, st_mode, st_uid)``
         with the pre-read identity.

    A same-bytes/different-inode substitution during the read window is
    detected at step 4 (the inode and/or mtime_ns change). The returned
    ``post_read_stat`` is the trusted identity carried forward to the
    pre-replace revalidation in :func:`_atomic_persist_pair`.

    This is defence-in-depth alongside the existing pre-replace
    revalidation: the pre-replace revalidation catches a substitution
    that happens AFTER the read window closes but BEFORE the first
    replace; this read-time check catches a substitution that happens
    DURING the read window (which would otherwise go undetected because
    the post-read bytes still match the pre-read bytes)."""
    pre_st = _lstat_identity(path, f"{role} (pre-read)")
    data = _read_bounded(path, role)
    # Narrow test seam: fires after the bounded read completes, before
    # the post-read identity revalidation. Production leaves this None.
    if _TEST_POST_READ_HOOK is not None:
        _TEST_POST_READ_HOOK(role)
    post_st = _lstat_identity(path, f"{role} (post-read)")
    if _identity_tuple(post_st) != _identity_tuple(pre_st):
        raise ExpectedSlotsAdapterError(
            f"{role}: source identity changed during read"
        )
    return data, post_st


# ---------------------------------------------------------------------------
# Projection reconstruction (lossless from the two sidecars).
# ---------------------------------------------------------------------------


def _reconstruct_projection(
    expected_doc: dict[str, Any], slots_doc: dict[str, Any]
) -> dict[str, Any]:
    """Reconstruct ``icp.shared.expected-slots-projection.v1`` losslessly.

    The expected sidecar carries per-node ``bbox``/``logicalBbox``/
    ``horizontalAnchor``/``impl``/``text``/``sourceText``/``textRuns``/
    ``fontSize``/``weight``/``colorHex``/``radius``. The slots sidecar is
    a flat ``{node_id: display_text}`` mapping. The projection carries the
    original ``bbox`` (not ``logicalBbox``), all pass-through fields, and
    ``slot = (id in slots_doc)``.

    Insertion order of ``expected_doc["nodes"]`` is preserved (Python dict
    iteration order is contractual per the JSON parse).

    Raises :class:`ExpectedSlotsAdapterError` on any shape divergence.
    """
    # Top-level shape: exact key set on expected.
    if not isinstance(expected_doc, dict):
        raise ExpectedSlotsAdapterError("expected: root must be an object")
    actual_keys = set(expected_doc.keys())
    if actual_keys != _EXPECTED_TOP_KEYS:
        missing = sorted(_EXPECTED_TOP_KEYS - actual_keys)
        extra = sorted(actual_keys - _EXPECTED_TOP_KEYS)
        raise ExpectedSlotsAdapterError(
            f"expected: top-level keys mismatch (missing={missing} extra={extra})"
        )
    # slots must be a flat object.
    if not isinstance(slots_doc, dict):
        raise ExpectedSlotsAdapterError("slots: root must be an object")

    nodes = expected_doc["nodes"]
    if not isinstance(nodes, dict):
        raise ExpectedSlotsAdapterError("expected.nodes: must be an object")

    # Every slot id must correspond to a node in expected.
    for slot_id in slots_doc:
        if not isinstance(slot_id, str):
            raise ExpectedSlotsAdapterError("slots: non-string key")
        if slot_id not in nodes:
            raise ExpectedSlotsAdapterError(
                "slots: id not present in expected nodes"
            )

    projection_nodes: list[dict[str, Any]] = []
    for nid, node in nodes.items():
        if not isinstance(nid, str) or not nid:
            raise ExpectedSlotsAdapterError("expected.nodes: non-string/empty id")
        if not isinstance(node, dict):
            raise ExpectedSlotsAdapterError("expected.nodes: node not an object")
        node_keys = set(node.keys())
        if node_keys != _EXPECTED_NODE_KEYS:
            missing = sorted(_EXPECTED_NODE_KEYS - node_keys)
            extra = sorted(node_keys - _EXPECTED_NODE_KEYS)
            raise ExpectedSlotsAdapterError(
                f"expected.nodes[{nid}]: keys mismatch (missing={missing} extra={extra})"
            )
        bbox = node["bbox"]
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise ExpectedSlotsAdapterError(
                f"expected.nodes[{nid}]: bbox must be a 4-number list"
            )
        projection_nodes.append(
            {
                "id": nid,
                "bbox": list(bbox),
                "horizontalAnchor": node["horizontalAnchor"],
                "impl": node["impl"],
                "text": node["text"],
                "sourceText": node["sourceText"],
                "textRuns": node["textRuns"],
                "fontSize": node["fontSize"],
                "weight": node["weight"],
                "colorHex": node["colorHex"],
                "radius": node["radius"],
                "slot": nid in slots_doc,
            }
        )

    return {
        "kind": KIND,
        "schemaVersion": SCHEMA_VERSION,
        "artboardWidth": expected_doc["artboardWidth"],
        "artboardHeight": expected_doc["artboardHeight"],
        "designPixelScale": expected_doc["designPixelScale"],
        "nodes": projection_nodes,
    }


# ---------------------------------------------------------------------------
# Atomic persist (prepare + fsync both temp files, revalidate, replace).
# ---------------------------------------------------------------------------


def _prepare_temp(
    sidecar_path: Path, rebuilt_bytes: bytes, role: str
) -> tuple[Path, int]:
    """Write ``rebuilt_bytes`` to a temp file in the same directory as
    ``sidecar_path``, fsync it, and return ``(temp_path, original_mode)``.

    The temp file is created via ``tempfile.NamedTemporaryFile`` in the
    sidecar's directory so the final ``os.replace`` is atomic on the same
    filesystem. The original file's mode is captured for restoration.
    """
    try:
        orig_st = sidecar_path.lstat()
    except OSError as exc:
        raise ExpectedSlotsAdapterError(
            f"{role}: cannot stat original: {type(exc).__name__}"
        ) from exc
    if not stat.S_ISREG(orig_st.st_mode):
        raise ExpectedSlotsAdapterError(f"{role}: original not a regular file")
    if sidecar_path.is_symlink():
        raise ExpectedSlotsAdapterError(f"{role}: refusing symlink original")
    original_mode = stat.S_IMODE(orig_st.st_mode)
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=str(sidecar_path.parent),
            prefix=".p25a2_",
            suffix=".tmp",
            delete=False,
        ) as tf:
            tf.write(rebuilt_bytes)
            tf.flush()
            os.fsync(tf.fileno())
        temp_path = Path(tf.name)
    except OSError as exc:
        raise ExpectedSlotsAdapterError(
            f"{role}: cannot prepare temp: {type(exc).__name__}"
        ) from exc
    # Apply the original mode to the temp file.
    try:
        os.chmod(temp_path, original_mode)
    except OSError as exc:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise ExpectedSlotsAdapterError(
            f"{role}: cannot chmod temp: {type(exc).__name__}"
        ) from exc
    return temp_path, original_mode


def _atomic_persist_pair(
    expected_path: Path,
    slots_path: Path,
    rebuilt_expected: bytes,
    rebuilt_slots: bytes,
    raw_expected: bytes,
    raw_slots: bytes,
    expected_identity: os.stat_result,
    slots_identity: os.stat_result,
) -> None:
    """Prepare + fsync both temp files, revalidate source identity, then
    replace both originals atomically.

    A crash between the two replaces is semantically safe: both payloads
    are byte-identical to the originals, so a reader sees the same bytes
    regardless of which replace completed.

    Source identity revalidation re-lstats both originals immediately
    before the first replace and requires:

    * the originals are still non-symlink regular files owned by the
      current user;
    * the originals' lstat identity tuples
      ``(st_dev, st_ino, st_size, st_mtime_ns, st_mode, st_uid)`` equal
      the identities captured right after the bounded read;
    * the re-read raw bytes still equal the originally-read bytes.

    Any divergence (a different inode with identical bytes, a different
    mtime, a size change, a mode change, an owner change, or a raw-byte
    change) aborts before any replace and cleans up both temp files.
    """
    expected_id = _identity_tuple(expected_identity)
    slots_id = _identity_tuple(slots_identity)
    # Narrow test seam: invoked after both temp files are prepared and
    # fsynced, before source identity revalidation. Tests use this to
    # simulate a source-identity change between read and replace.
    temp_expected: Path | None = None
    temp_slots: Path | None = None
    try:
        temp_expected, _mode_e = _prepare_temp(
            expected_path, rebuilt_expected, "expected"
        )
        temp_slots, _mode_s = _prepare_temp(
            slots_path, rebuilt_slots, "slots"
        )
        # No partial replace before both temp files are prepared.
        if _TEST_PRE_REPLACE_HOOK is not None:
            _TEST_PRE_REPLACE_HOOK()
        # Revalidate source identity: lstat both originals again and
        # require exact identity equality (catches a different inode with
        # identical bytes) PLUS raw-byte equality (catches a same-inode
        # content rewrite, which on most filesystems also bumps mtime).
        cur_expected_st = _lstat_identity(
            expected_path, "expected (pre-replace)"
        )
        cur_slots_st = _lstat_identity(slots_path, "slots (pre-replace)")
        if _identity_tuple(cur_expected_st) != expected_id:
            raise ExpectedSlotsAdapterError(
                "expected: source identity changed during read"
            )
        if _identity_tuple(cur_slots_st) != slots_id:
            raise ExpectedSlotsAdapterError(
                "slots: source identity changed during read"
            )
        try:
            current_expected = expected_path.read_bytes()
            current_slots = slots_path.read_bytes()
        except OSError as exc:
            raise ExpectedSlotsAdapterError(
                f"source identity revalidation failed: {type(exc).__name__}"
            ) from exc
        if current_expected != raw_expected:
            raise ExpectedSlotsAdapterError(
                "expected: source bytes changed during read"
            )
        if current_slots != raw_slots:
            raise ExpectedSlotsAdapterError(
                "slots: source bytes changed during read"
            )
        # Replace both. Each os.replace is atomic on the same filesystem.
        try:
            os.replace(temp_expected, expected_path)
            temp_expected = None
            os.replace(temp_slots, slots_path)
            temp_slots = None
        except OSError as exc:
            raise ExpectedSlotsAdapterError(
                f"replace failed: {type(exc).__name__}"
            ) from exc
    finally:
        # Clean up any temp file that was not replaced (failure path).
        for temp in (temp_expected, temp_slots):
            if temp is not None:
                try:
                    temp.unlink()
                except OSError:
                    pass


# ---------------------------------------------------------------------------
# Core run.
# ---------------------------------------------------------------------------


def _run(
    project_root: Path,
    canvas: Path,
    run_root: Path | None = None,
    feature_id: str | None = None,
) -> dict[str, Any]:
    """Read both sidecars, reconstruct the projection, rebuild via
    SharedCore, require byte parity, atomically persist. Returns a stable
    summary dict (no raw sidecar contents).

    When ``run_root`` and ``feature_id`` are both supplied (and validated
    upstream), additionally publish the canonical projection bytes to
    ``<run_root>/expected_slots_projections/<feature_id>.json`` AFTER
    the parity check has passed but BEFORE the legacy sidecar replace.
    The projection-output preconditions and canonical bytes are fully
    validated before the first legacy-sidecar replace so a publication
    failure does not leave the sidecars mid-replace; if publication
    fails after the sidecars were replaced, the sidecars remain
    semantically unchanged (their old/new bytes are identical), and the
    adapter reports failure without fabricating success.
    """
    expected_path = Path(str(canvas) + ".expected.json")
    slots_path = Path(str(canvas) + ".slots.json")
    # Read-time identity window: each sidecar's identity is captured
    # before its bounded read, re-lstat'd immediately after the read
    # (with an optional test seam in between), and required to be equal.
    # The post-read identities become the trusted identities carried
    # forward to the pre-replace revalidation. This detects a same-bytes/
    # different-inode substitution DURING the read window; the existing
    # pre-replace revalidation detects one AFTER the read window closes.
    raw_expected, expected_st_trusted = _read_with_identity_check(
        expected_path, "expected"
    )
    raw_slots, slots_st_trusted = _read_with_identity_check(
        slots_path, "slots"
    )

    # Strict decode (UTF-8 + JSON + dup-key rejection).
    expected_doc = _decode_json_strict(raw_expected, "expected")
    slots_doc = _decode_json_strict(raw_slots, "slots")

    # Reconstruct the projection.
    projection = _reconstruct_projection(expected_doc, slots_doc)

    # Load SharedCore and rebuild both sidecar bytes.
    projection_module = _load_projection_module()
    try:
        rebuilt_expected, rebuilt_slots = projection_module.build_legacy_bytes(
            projection
        )
    except projection_module.ProjectionValidationError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ExpectedSlotsAdapterError(
            f"shared_core build failed: {type(exc).__name__}"
        ) from exc

    # Byte parity: both rebuilt sidecars must equal the original raw bytes.
    if rebuilt_expected != raw_expected:
        raise ExpectedSlotsAdapterError(
            "expected: rebuilt bytes diverge from original (parity failure)"
        )
    if rebuilt_slots != raw_slots:
        raise ExpectedSlotsAdapterError(
            "slots: rebuilt bytes diverge from original (parity failure)"
        )

    # P2.5b: projection artifact publication. The canonical projection
    # bytes are produced from the SAME validated projection above via
    # SharedCore build_projection_bytes; the publication happens BEFORE
    # the legacy sidecar replace so a publication failure leaves the
    # originals untouched. If publication succeeds, the sidecar replace
    # then runs as usual (byte-identical, so it is a no-op on bytes).
    projection_artifact_rel: str | None = None
    if run_root is not None and feature_id is not None:
        try:
            projection_bytes = (
                projection_module.build_projection_bytes(projection)
            )
        except projection_module.ProjectionValidationError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ExpectedSlotsAdapterError(
                f"shared_core projection_bytes failed: "
                f"{type(exc).__name__}"
            ) from exc
        projection_artifact_rel = _publish_projection_artifact(
            run_root, feature_id, projection_bytes
        )

    # Atomically persist the byte-identical output. The persist function
    # re-lstats both originals immediately before the first replace and
    # requires identity AND byte equality against the trusted post-read
    # identities captured above; any divergence aborts and cleans both
    # temps.
    _atomic_persist_pair(
        expected_path, slots_path,
        rebuilt_expected, rebuilt_slots,
        raw_expected, raw_slots,
        expected_st_trusted, slots_st_trusted,
    )

    # Stable summary (no raw sidecar contents).
    summary: dict[str, Any] = {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "node_count": len(projection["nodes"]),
        "slot_count": sum(1 for n in projection["nodes"] if n["slot"]),
        "expected_bytes": len(raw_expected),
        "slots_bytes": len(raw_slots),
        "expected_sha256": _sha256_bytes(raw_expected),
        "slots_sha256": _sha256_bytes(raw_slots),
    }
    if projection_artifact_rel is not None:
        # Stable run-relative projection artifact path. Never emit the
        # absolute supplied run_root or raw projection content.
        summary["projection_artifact_rel"] = projection_artifact_rel
    return summary


# ---------------------------------------------------------------------------
# CLI / public main().
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str]) -> tuple[str, str, str | None, str | None]:
    """Parse the EXACT CLI arguments. Raises SystemExit on any usage
    error, including an unknown flag.

    Required tokens: ``--project-root <value>`` and ``--canvas <value>``.
    Optional pair: ``--run-root <value>`` and ``--feature-id <value>``,
    which must appear together or both be absent. Any extra token
    (unknown flag, extra positional) is rejected so an unknown argument
    can never be silently accepted and the adapter never reaches the
    sidecars.
    """
    ap = argparse.ArgumentParser(
        prog="flutter_expected_slots_adapter_v1.py",
        description=(
            "P2.5a2/P2.5b Flutter expected/slots adapter: reconstructs "
            "the accepted SharedCore projection from the frozen "
            "generate_canvas sidecars, proves byte parity, atomically "
            "persists the byte-identical SharedCore output, and "
            "(optionally) publishes the canonical projection artifact."
        ),
        add_help=True,
        # Exact parsing: argparse rejects unknown flags AND extra
        # positionals by default with parse_args. We do not use
        # parse_known_args anywhere.
    )
    ap.add_argument("--project-root", required=True, dest="project_root")
    ap.add_argument("--canvas", required=True)
    ap.add_argument("--run-root", dest="run_root", default=None)
    ap.add_argument("--feature-id", dest="feature_id", default=None)
    parsed = ap.parse_args(argv)
    run_root = parsed.run_root
    feature_id = parsed.feature_id
    # Optional pair: both or neither.
    if (run_root is None) != (feature_id is None):
        ap.error(
            "--run-root and --feature-id must appear together or both be absent"
        )
    return parsed.project_root, parsed.canvas, run_root, feature_id


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Parses ``--project-root <abs dir>`` and ``--canvas <abs .dart path>``
    plus the optional ``--run-root <abs dir>`` / ``--feature-id <id>``
    pair (both or neither), runs the adapter, and prints a stable JSON
    summary to stdout on success. On any failure, prints the type name
    to stderr (no traceback, no raw input/path/file-content leak) and
    returns a non-zero exit code.
    """
    if argv is None:
        argv = sys.argv[1:]
    try:
        project_root_str, canvas_str, run_root_str, feature_id_str = _parse_args(
            list(argv)
        )
    except SystemExit as exc:
        # argparse already printed a sanitized usage message.
        return int(exc.code) if isinstance(exc.code, int) else 2

    try:
        project_root = _validate_project_root(project_root_str)
        canvas = _validate_canvas(canvas_str, project_root)
        # Optional projection-publish pair.
        run_root: Path | None = None
        feature_id: str | None = None
        if run_root_str is not None and feature_id_str is not None:
            run_root = _validate_run_root(run_root_str, project_root)
            feature_id = _validate_feature_id(feature_id_str)
        summary = _run(project_root, canvas, run_root, feature_id)
    except ExpectedSlotsAdapterError as exc:
        # Type-only message; no traceback, no raw input leak.
        sys.stderr.write(f"ExpectedSlotsAdapterError: {exc}\n")
        return 1
    except Exception as exc:  # noqa: BLE001
        # Convert any unexpected exception to a type-only message.
        sys.stderr.write(f"ExpectedSlotsAdapterError: unexpected {type(exc).__name__}\n")
        return 1

    sys.stdout.write(json.dumps(summary, ensure_ascii=False, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
