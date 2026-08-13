#!/usr/bin/env python3
"""ICP P1b frozen selection manifest freezer.

Builds and durably persists the canonical ``icp.selection_manifest.v1``
evidence document for one selection batch. The manifest is the durable
contract between read-only selection and any later claim/export/writeback; it
must exist on disk before any task row is mutated, and it must never be
overwritten once frozen.

Hard rules enforced here:

* Roots are derived internally from the resolved profile/project root and the
  internally-generated ``batch_id`` — never read from run-config:

    * Flutter: state root ``<project>/.iff``,
      run root ``<project>/.iff/icp_runs/<batch_id>``.
    * Vue: state root ``<project>/.icp``,
      run root ``<project>/.icp/runs/<batch_id>``.

  The freezer never follows a symlinked project root, state root
  (``.iff`` / ``.icp``), or derived run-parent (``icp_runs`` / ``runs``), and
  never creates a manifest outside the ordinary resolved project directory.
  A missing project root is not created by the freezer; only the derived
  state/run roots beneath an existing ordinary project root are created
  stepwise (project root -> state root -> run parent -> batch run root),
  each re-checked for ordinary-directory status so a pre-existing symlink
  cannot be treated as a directory.

* No ``state_root``, ``run_root``, registry path, script path, command, env,
  or executable data is accepted from run-config. The low-level freezer
  accepts only an explicit ``batch_id`` (so unit tests can pin it) and
  optional in-memory registries. No public or lower-level manifest API
  accepts an externally supplied scripts directory/path: runtime script
  digests are computed from the fixed ``icp/scripts`` tree only.
* Schema ``icp.selection_manifest.v1`` contains exactly the frozen evidence:
  schema/version/kind, ``batch_id``, resolved IDs and absolute paths,
  internal registry digest, selected profile digest, rules digest (SHA-256 of
  the fixed ``icp/SKILL.md`` bytes), runtime-script digests (the complete P1
  execution set), capability set, actual batch size, candidate
  identities/evidence, ``state_root``, ``run_root``.
* All digests are computed internally from fixed ICP files / registry data;
  there is no external digest or path override.
* ``batch_id`` is restricted to ``^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$``; in
  particular ``.`` and ``..`` are rejected with ``invalid_input`` and can
  never collapse or escape the run directory.
* The batch run directory is created exclusively. An existing run root or
  manifest is ``selection_manifest_conflict`` and is never overwritten or
  reused. Manifest publication is atomic and no-clobber under a race: a
  same-directory temp file is written and fsynced, then atomically
  ``os.link``-ed to the absent destination, the owned temp is unlinked, then
  the directory is fsynced (in that observable order); ``EEXIST`` is
  normalized to ``selection_manifest_conflict`` and only invocation-owned
  temporary artifacts are cleaned.
* Deterministic bytes: identical explicit inputs (config, candidates,
  batch_id, registries) produce byte-identical manifests. No timestamp is
  emitted.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

import icp_common

SCHEMA_VERSION = 1
KIND = "icp.selection_manifest.v1"
MANIFEST_FILENAME = "selection-manifest.json"

# Fixed ICP scripts/roots; runtime digests come from this tree only.
_SCRIPTS_DIR = Path(__file__).resolve().parent
_ICP_ROOT = _SCRIPTS_DIR.parent
_SKILL_MD_PATH = _ICP_ROOT / "SKILL.md"

# Platform-specific state/run-root derivation. Keys are platform IDs; values
# are (state_dirname, run_subpath) tuples. The state root is a directory
# directly beneath the project root; the run root is beneath it.
_PLATFORM_ROOTS: dict[str, tuple[str, str]] = {
    "flutter": (".iff", str(Path(".iff") / "icp_runs")),
    "vue": (".icp", str(Path(".icp") / "runs")),
    "nextjs": (".icp", str(Path(".icp") / "runs")),
    "ios-swift": (".icp", str(Path(".icp") / "runs")),
    "ios-objc": (".icp", str(Path(".icp") / "runs")),
    "android-java": (".icp", str(Path(".icp") / "runs")),
    "android-kotlin": (".icp", str(Path(".icp") / "runs")),
}

# Batch ids must be path-safe and cannot collapse/escape the run
# directory. The grammar is enforced with :meth:`re.Pattern.fullmatch`
# (NOT :meth:`re.Pattern.match`): Python's ``$`` anchor may match before
# a final trailing newline, so ``re.match(r'...$')`` would accept a
# value ending in ``\n``. ``fullmatch`` is the exact whole-string
# contract; macOS permits a directory name containing a newline, so
# this is a real on-disk attack surface, not a theoretical one.
_BATCH_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")

# Fixed list of ICP runtime scripts whose bytes are part of the manifest's
# runtime-script digests: the complete P1 execution set. All paths are
# relative to the fixed ICP scripts dir.
_RUNTIME_SCRIPTS: tuple[str, ...] = (
    "icp_common.py",
    "resolve_run_config.py",
    "preflight_selection.py",
    "csv_task_source.py",
    "freeze_selection_manifest.py",
    "prepare_selection.py",
    str(Path("task_sources") / "__init__.py"),
    str(Path("task_sources") / "csv_row_status_v1.py"),
)


class ManifestFreezeError(RuntimeError):
    """Structured freezer failure carrying a public ``code``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Digest helpers.
# ---------------------------------------------------------------------------


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return icp_common.canonical_json_bytes(payload)


def _digest_label(hexdigest: str) -> str:
    return f"sha256:{hexdigest}"


# ---------------------------------------------------------------------------
# Root derivation (internal only).
# ---------------------------------------------------------------------------


def derive_roots(platform: str, project_root: Path | str, batch_id: str) -> tuple[Path, Path]:
    """Return ``(state_root, run_root)`` for ``platform`` / ``project_root``.

    Pure derivation: no input from run-config beyond the resolved platform and
    project root. Raises :class:`ManifestFreezeError` (code ``invalid_input``)
    for an unknown platform or an unsafe ``batch_id``. Batch ids are
    restricted to ``^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$`` so ``.``, ``..``,
    slashes, backslashes, whitespace, and overlong forms can never collapse or
    escape the run directory.
    """
    if platform not in _PLATFORM_ROOTS:
        raise ManifestFreezeError(
            icp_common.INVALID_INPUT,
            f"cannot derive roots for unsupported platform {platform!r}",
        )
    if not isinstance(batch_id, str) or not _BATCH_ID_RE.fullmatch(batch_id):
        raise ManifestFreezeError(
            icp_common.INVALID_INPUT,
            f"batch_id must match ^[A-Za-z0-9][A-Za-z0-9_-]{{0,127}}$, got {batch_id!r}",
        )
    state_dirname, run_subpath = _PLATFORM_ROOTS[platform]
    project = Path(project_root)
    state_root = project / state_dirname
    run_root = project / run_subpath / batch_id
    return state_root, run_root


# ---------------------------------------------------------------------------
# Internal digests computed from fixed ICP files / registry data.
# ---------------------------------------------------------------------------


def _registry_digest(registries: dict[str, Any]) -> str:
    """Digest over the canonical encoding of the full registries document."""
    return _sha256_bytes(_canonical_bytes(registries))


def _selected_profile_digest(registries: dict[str, Any], platform: str) -> str:
    """Digest over the registry entry for the selected platform."""
    platforms = registries.get("platforms", {})
    if platform not in platforms:
        raise ManifestFreezeError(
            icp_common.INVALID_INPUT,
            f"selected platform {platform!r} is not in registries",
        )
    return _sha256_bytes(_canonical_bytes({"platform": platform, "entry": platforms[platform]}))


def _rules_digest() -> str:
    """Digest over the fixed ``icp/SKILL.md`` file bytes.

    This is the frozen rules contract for the slice; it does not depend on the
    registries argument so a registry override can never change the rules
    evidence embedded in the manifest.
    """
    if not _SKILL_MD_PATH.is_file():
        raise ManifestFreezeError(
            icp_common.INVALID_INPUT,
            f"rules source missing while freezing manifest: {_SKILL_MD_PATH}",
        )
    return _sha256_file(_SKILL_MD_PATH)


def _runtime_script_digests() -> dict[str, str]:
    """SHA-256 of every fixed runtime script under the fixed ICP scripts dir.

    Missing files raise :class:`ManifestFreezeError` so the manifest can never
    silently lose provenance for a runtime script that has been deleted. No
    external scripts directory is accepted.
    """
    out: dict[str, str] = {}
    for rel in _RUNTIME_SCRIPTS:
        path = _SCRIPTS_DIR / rel
        if not path.is_file():
            raise ManifestFreezeError(
                icp_common.INVALID_INPUT,
                f"runtime script missing while freezing manifest: {rel}",
            )
        out[rel] = _digest_label(_sha256_file(path))
    return out


def _capability_set(registries: dict[str, Any]) -> dict[str, str]:
    """The capability map (operation id -> capability state)."""
    capabilities = dict(registries.get("capabilities", {}))
    return capabilities


def _candidate_evidence(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project the candidate list to the exact frozen evidence fields."""
    out: list[dict[str, Any]] = []
    for cand in candidates:
        out.append(
            {
                "row_index": cand.get("row_index"),
                "title": cand.get("title", ""),
                "status": cand.get("status", ""),
                "design_url": cand.get("design_url", ""),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Atomic no-clobber publication (temp + fsync + os.link + dir fsync).
# ---------------------------------------------------------------------------


def _publish_manifest_exclusive(manifest_path: Path, payload: bytes) -> None:
    """Publish ``payload`` to ``manifest_path`` atomically and without clobber.

    Algorithm (observable order on success):

    1. refuse a symlink destination;
    2. allocate a same-directory temp file via ``mkstemp``;
    3. write + flush + ``fsync`` the temp;
    4. atomically ``os.link`` the temp to the destination;
    5. unlink the owned temp;
    6. ``fsync`` the parent directory.

    ``os.replace`` is deliberately NOT used: it would silently overwrite a
    destination created after the explicit existence check. ``os.link`` raises
    ``FileExistsError`` if the destination exists (including a racing
    sentinel), which is normalized by the caller to
    ``selection_manifest_conflict``. Only invocation-owned temporary artifacts
    (the temp file) are ever cleaned here.
    """
    manifest_path = Path(manifest_path)
    if manifest_path.is_symlink():
        raise ManifestFreezeError(
            icp_common.SELECTION_MANIFEST_CONFLICT,
            f"refusing symlink manifest path: {manifest_path}",
        )
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{manifest_path.name}.", suffix=".tmp", dir=str(manifest_path.parent)
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(tmp, manifest_path)
        except FileExistsError as exc:
            raise _RaceConflict(
                f"manifest destination appeared during publication: {manifest_path}"
            ) from exc
        # Unlink the owned temp BEFORE the directory fsync so the durability
        # order is: temp fsync -> link -> temp unlink -> directory fsync.
        try:
            tmp.unlink()
        except OSError:
            pass
        dir_fd = os.open(manifest_path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except _RaceConflict:
        # On a race conflict the temp is cleaned in the finally below; the
        # foreign manifest survives. Do NOT fall through to the normal cleanup
        # path because the directory fsync has not run yet.
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


class _RaceConflict(ManifestFreezeError):
    """Internal sentinel raised by the publisher when ``os.link`` hits EEXIST.

    Subclassed so the caller can distinguish a race conflict (do not clean the
    run root; the foreign manifest must survive) from other failures.
    """

    def __init__(self, message: str) -> None:
        super().__init__(icp_common.SELECTION_MANIFEST_CONFLICT, message)


# ---------------------------------------------------------------------------
# Symlink-safe directory helpers.
# ---------------------------------------------------------------------------

import stat as _stat


def _is_ordinary_dir(path: Path) -> bool:
    """True iff ``path`` exists, is not a symlink, and is a directory."""
    if path.is_symlink():
        return False
    try:
        st = path.stat()
    except (OSError, ValueError):
        return False
    return _stat.S_ISDIR(st.st_mode)


def _assert_ordinary_project_root(project_root: Path) -> None:
    """Reject a missing, symlinked, or non-directory project root.

    The freezer never creates the project root; it must already exist as an
    ordinary directory. Uses ``project_preflight_failed`` for invalid direct
    roots (a missing or non-dir project root is a project-level preflight
    failure, not a manifest conflict).
    """
    if project_root.is_symlink():
        raise ManifestFreezeError(
            icp_common.PROJECT_PREFLIGHT_FAILED,
            f"project root must not be a symlink: {project_root}",
        )
    try:
        st = project_root.stat()
    except FileNotFoundError as exc:
        raise ManifestFreezeError(
            icp_common.PROJECT_PREFLIGHT_FAILED,
            f"project root does not exist (freezer does not create it): {project_root}",
        ) from exc
    except OSError as exc:
        raise ManifestFreezeError(
            icp_common.PROJECT_PREFLIGHT_FAILED,
            f"cannot stat project root: {exc}",
        ) from exc
    if not _stat.S_ISDIR(st.st_mode):
        raise ManifestFreezeError(
            icp_common.PROJECT_PREFLIGHT_FAILED,
            f"project root is not a directory: {project_root}",
        )


def _ensure_ordinary_dir(path: Path, *, label: str) -> bool:
    """Validate or create ``path`` as an ordinary (non-symlink) directory.

    If ``path`` exists it must be an ordinary directory (not a symlink, not a
    file). If it does not exist it is created as a single directory (no
    ``parents=True``); the parent must already exist. Returns True if this
    call created the directory.

    Raises :class:`ManifestFreezeError` (code ``selection_manifest_conflict``)
    if ``path`` is a symlink or an unexpected file, so the freezer never
    follows a symlinked state root or run parent out of the project tree.
    """
    if path.is_symlink():
        raise ManifestFreezeError(
            icp_common.SELECTION_MANIFEST_CONFLICT,
            f"refusing symlink {label}: {path}",
        )
    try:
        st = path.stat()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise ManifestFreezeError(
            icp_common.SELECTION_MANIFEST_CONFLICT,
            f"cannot stat {label} {path}: {exc}",
        ) from exc
    else:
        if not _stat.S_ISDIR(st.st_mode):
            raise ManifestFreezeError(
                icp_common.SELECTION_MANIFEST_CONFLICT,
                f"{label} exists and is not a directory: {path}",
            )
        # Re-check: a symlink could have appeared between is_symlink() and
        # stat(); stat() follows symlinks, so if lstat says symlink but stat
        # says dir, we already caught it above.
        return False
    # Does not exist; create a single ordinary directory.
    try:
        path.mkdir(parents=False, exist_ok=False)
    except FileExistsError as exc:
        # Race: appeared between our check and mkdir. Re-validate.
        if not _is_ordinary_dir(path):
            raise ManifestFreezeError(
                icp_common.SELECTION_MANIFEST_CONFLICT,
                f"{label} appeared as non-ordinary during creation: {path}",
            ) from exc
        return False
    except FileNotFoundError as exc:
        raise ManifestFreezeError(
            icp_common.SELECTION_MANIFEST_CONFLICT,
            f"parent of {label} does not exist: {path}",
        ) from exc
    except OSError as exc:
        raise ManifestFreezeError(
            icp_common.SELECTION_MANIFEST_CONFLICT,
            f"cannot create {label} {path}: {exc}",
        ) from exc
    # Re-check after creation so a pre-existing symlink cannot be treated as
    # a directory.
    if not _is_ordinary_dir(path):
        raise ManifestFreezeError(
            icp_common.SELECTION_MANIFEST_CONFLICT,
            f"{label} is not an ordinary directory after creation: {path}",
        )
    return True


# ---------------------------------------------------------------------------
# Manifest construction.
# ---------------------------------------------------------------------------


def build_manifest_payload(
    *,
    resolved_config: dict[str, Any],
    candidates: list[dict[str, Any]],
    batch_id: str,
    registries: dict[str, Any],
) -> tuple[dict[str, Any], Path, Path, bytes]:
    """Build the canonical manifest payload + derived roots + encoded bytes.

    Pure: does not touch disk (digests are read from the fixed ICP files at
    call time, which is part of computing the frozen evidence). Returns
    ``(payload, state_root, run_root, encoded_bytes)``.

    No ``scripts_dir`` parameter is accepted: runtime script digests come from
    the fixed ``icp/scripts`` tree only. ``resolved_config`` is the strict
    resolved run-config (only ``platform`` / ``project_root`` feed the
    manifest; no roots/paths/commands are read from it).
    """
    if not isinstance(resolved_config, dict):
        raise ManifestFreezeError(
            icp_common.INVALID_INPUT, "resolved_config must be a JSON object"
        )
    platform = resolved_config.get("platform")
    project_root = resolved_config.get("project_root")
    if not isinstance(platform, str) or platform == "":
        raise ManifestFreezeError(
            icp_common.INVALID_INPUT, "resolved_config.platform must be a non-empty string"
        )
    if not isinstance(project_root, str) or project_root == "":
        raise ManifestFreezeError(
            icp_common.INVALID_INPUT, "resolved_config.project_root must be a non-empty string"
        )

    state_root, run_root = derive_roots(platform, project_root, batch_id)

    # Frozen resolved-IDs block: only the public resolved fields, no
    # registry/script/command/env overrides ever enter the manifest.
    resolved_block = {
        "task_source": resolved_config.get("task_source"),
        "task_ref": resolved_config.get("task_ref"),
        "design_source": resolved_config.get("design_source"),
        "platform": platform,
        "profile": resolved_config.get("profile"),
        "project_root": project_root,
    }

    payload: dict[str, Any] = {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "batch_id": batch_id,
        "resolved": resolved_block,
        "registry_digest": _digest_label(_registry_digest(registries)),
        "selected_profile_digest": _digest_label(
            _selected_profile_digest(registries, platform)
        ),
        "rules_digest": _digest_label(_rules_digest()),
        "runtime_script_digests": _runtime_script_digests(),
        "capabilities": _capability_set(registries),
        "actual_batch_size": len(candidates),
        "candidates": _candidate_evidence(candidates),
        "state_root": str(state_root),
        "run_root": str(run_root),
    }
    encoded = _canonical_bytes(payload)
    return payload, state_root, run_root, encoded


# ---------------------------------------------------------------------------
# Public freeze entrypoint (durability boundary).
# ---------------------------------------------------------------------------


def freeze_selection_manifest(
    *,
    resolved_config: dict[str, Any],
    candidates: list[dict[str, Any]],
    batch_id: str,
    registries: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Freeze a ``icp.selection_manifest.v1`` document to disk and return its ack.

    Roots are created stepwise and symlink-safe: the project root must already
    exist as an ordinary directory (the freezer never creates it); the state
    root and run parent are validated/created as ordinary directories (a
    symlink at any of these levels is rejected); the batch run root is created
    exclusively without ``parents=True`` and re-checked after creation. An
    existing run root or manifest is :class:`ManifestFreezeError` with code
    ``selection_manifest_conflict`` and is never overwritten or reused.
    Manifest publication is atomic and no-clobber under a race (temp fsync ->
    ``os.link`` -> owned temp unlink -> directory fsync, in that observable
    order); a destination created after the explicit existence check survives
    byte-for-byte and surfaces ``selection_manifest_conflict``.

    On a race conflict only invocation-owned temporary artifacts are cleaned
    (the temp file); the foreign manifest and the run directory it occupies
    are left untouched. On other failures the run directory this call created
    is removed only if it is empty. No task row is ever mutated by this
    function, and no ``scripts_dir``/path override is accepted.

    Returns an ``icp.selection_manifest.v1`` ack including the manifest path,
    the derived roots, the canonical bytes' SHA-256, and the actual batch
    size.
    """
    if registries is None:
        registries = icp_common.load_registries()

    payload, state_root, run_root, encoded = build_manifest_payload(
        resolved_config=resolved_config,
        candidates=candidates,
        batch_id=batch_id,
        registries=registries,
    )

    run_root_path = Path(run_root)
    state_root_path = Path(state_root)
    project_root_path = Path(resolved_config["project_root"])
    run_parent_path = run_root_path.parent
    created_run_root = False

    # Stepwise symlink-safe directory creation. The freezer never follows a
    # symlinked project root, state root (.iff/.icp), or run parent
    # (icp_runs/runs), and never creates the project root itself.
    _assert_ordinary_project_root(project_root_path)
    _ensure_ordinary_dir(state_root_path, label="state root")
    _ensure_ordinary_dir(run_parent_path, label="run parent")

    # Exclusive create of the batch run root (no parents=True; the parent is
    # already validated above). Existing root is a conflict and is never
    # reused.
    if run_root_path.is_symlink():
        raise ManifestFreezeError(
            icp_common.SELECTION_MANIFEST_CONFLICT,
            f"refusing symlink batch run root: {run_root_path}",
        )
    try:
        run_root_path.mkdir(parents=False, exist_ok=False)
        created_run_root = True
    except FileExistsError as exc:
        raise ManifestFreezeError(
            icp_common.SELECTION_MANIFEST_CONFLICT,
            f"batch run root already exists and cannot be reused: {run_root_path}",
        ) from exc
    except OSError as exc:
        raise ManifestFreezeError(
            icp_common.SELECTION_MANIFEST_CONFLICT,
            f"cannot create batch run root {run_root_path}: {exc}",
        ) from exc
    # Re-check containment/ordinary-directory status after creation.
    if not _is_ordinary_dir(run_root_path):
        raise ManifestFreezeError(
            icp_common.SELECTION_MANIFEST_CONFLICT,
            f"batch run root is not an ordinary directory after creation: {run_root_path}",
        )

    manifest_path = run_root_path / MANIFEST_FILENAME
    # Explicit existence check for a clear error message; the real no-clobber
    # guarantee is the atomic os.link in _publish_manifest_exclusive.
    if manifest_path.exists():
        raise ManifestFreezeError(
            icp_common.SELECTION_MANIFEST_CONFLICT,
            f"manifest already exists at {manifest_path}",
        )

    try:
        _publish_manifest_exclusive(manifest_path, encoded)
    except _RaceConflict:
        # A destination appeared after the existence check. The foreign
        # manifest must survive byte-for-byte; clean only the owned temp
        # (already done in the publisher's finally) and leave the run root in
        # place. Do NOT remove the manifest-named file: this invocation never
        # created it.
        raise
    except ManifestFreezeError:
        _cleanup_owned_run_root(run_root_path, created_run_root)
        raise
    except OSError as exc:
        _cleanup_owned_run_root(run_root_path, created_run_root)
        raise ManifestFreezeError(
            icp_common.SELECTION_MANIFEST_CONFLICT,
            f"failed to publish manifest {manifest_path}: {exc}",
        ) from exc

    digest = _sha256_bytes(encoded)
    return {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "batch_id": batch_id,
        "manifest_path": str(manifest_path),
        "state_root": str(state_root_path),
        "run_root": str(run_root_path),
        "manifest_sha256": digest,
        "actual_batch_size": len(candidates),
    }


def _cleanup_owned_run_root(run_root: Path, created: bool) -> None:
    """Remove an invocation-owned run directory only if it is empty.

    Never unlinks any file (a manifest-named file present after a publish
    failure is foreign and must survive). Only ``rmdir`` is attempted, and
    only on a directory this invocation created; foreign files inside cause
    the ``rmdir`` to fail safely and the directory is left in place.
    """
    if not created:
        return
    try:
        run_root.rmdir()
    except OSError:
        # Non-empty or otherwise und removable: leave it in place rather than
        # risk removing a foreign artifact.
        pass


def read_manifest(manifest_path: Path | str) -> dict[str, Any]:
    """Read and decode a frozen selection manifest from disk."""
    path = Path(manifest_path)
    return json.loads(path.read_text(encoding="utf-8"))
