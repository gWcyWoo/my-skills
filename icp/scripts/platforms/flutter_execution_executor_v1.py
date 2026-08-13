#!/usr/bin/env python3
"""ICP P2e2b fixed-argv Flutter execution executor.

This module is the first activation slice. Given an authorization
produced and verified by P2e2a
(``icp.flutter-execution-authorization-candidate``), it executes the
exact ordered operation-plan steps already bound by that candidate,
consumes the authorization nonce exactly once, and leaves durable
receipts that make every success, failure, timeout, launch error, or
uncertain/crashed attempt non-replayable.

Public Python API (no CLI):

* ``execute_authorization(authorization, *, expected_manifest_path,
     expected_manifest_sha256, expected_binding_digest,
     expected_authorization_digest) -> dict``

Only this function plus the module-local typed exception
:class:`FlutterExecutionExecutorError` may be public.

Mandatory pre-claim verification (truthful transitive-preflight
boundary):

* ``execute_authorization`` calls
  :func:`flutter_execution_authorization_v1.verify_authorization`
  with all four caller-held expected values; none may default, be
  inferred from the untrusted document, or be optional. Fail closed
  on any verification error.
* That verify chain re-attests the embedded binding through
  :func:`flutter_execution_binding_v1.verify_binding`, which re-runs
  the fixed read-only Flutter project preflight
  ``subprocess.run([resolved_flutter, "--version", "--machine"],
  shell=False, ...)``. Therefore ``execute_authorization`` CAN cause
  that one fixed, read-only child process to run, and CAN fail if
  that fixed preflight fails. This is the only transitive child
  process surface in the verification chain; it is owned by
  ``flutter_project_preflight_v1.preflight``, not by this module's
  spawn surface.
* Before the first nonce claim, a failure of that fixed transitive
  preflight raises before any receipt is written. This preflight is
  not an operation-plan command.

Durable one-time nonce claim:

* The run root is derived from the freshly verified candidate's
  embedded ``selection_verification.run_root`` and cross-checked
  against ``Path(selection_manifest_path).parent``. No caller
  override.
* The fixed receipt directory is
  ``<run_root>/.icp-execution-receipts-v1/``. The run root is opened
  as a directory fd with ``O_NOFOLLOW | O_CLOEXEC`` where supported;
  the receipt directory is opened relative to that fd and rejected if
  it is a symlink, non-directory, owned by another uid, or has
  permissions broader than ``0700``.
* The claim ``<nonce>.claim.json`` is created atomically relative to
  the receipt-directory fd using
  ``O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC`` where supported and
  mode ``0600``; canonical UTF-8 JSON; fsync of file and directory.
  A claim that was created but only partially written still consumes
  the nonce forever. Replays are rejected without spawning any step.
* The terminal result ``<nonce>.result.json`` is created as a
  separate ``O_EXCL``, mode-``0600``, canonical JSON file with fsync
  of file and directory. If the executor crashes before terminal
  persistence, the claim-only state is explicitly
  ``indeterminate/consumed``, never retryable.
* Claim payload binds: schema/kind, execution nonce, expected
  authorization digest, binding digest, selection manifest path/SHA,
  platform/profile/operation/port IDs, and the ordered step-
  authorization digests. Result payload binds the claim digest and
  expected authorization digest and contains only sanitized
  execution metadata. Raw stdout/stderr is never persisted.

Exact ordered execution:

* After the claim, the embedded binding plan is executed serially and
  the loop stops at the first non-success.
* Immediately before **every** operation-plan spawn,
  ``verify_authorization`` is re-run (re-running the fixed transitive
  Flutter version preflight), the plan step is required to equal its
  same-index step authorization (step id, primitive, primitive
  path/SHA, argv digest, cwd, timeout, executable path/SHA, and step-
  authorization digest), the bound argv is copied to an immutable
  local tuple (every element a string, ``argv[0] == sys.executable``
  exactly with the lexical Homebrew symlink valid, ``argv[1]`` equal
  to the bound primitive path exactly, no NULs), ``sys.executable``
  and the primitive script are re-hashed, the cwd is re-checked, and
  the tuple is spawned with ``shell=False``, exact cwd, exact
  timeout, ``stdin=DEVNULL``, ``close_fds=True``, and a new process
  session/group.

Environment policy (truthful trust boundary):

* There is no caller-provided environment. The executor builds an
  environment from the trusted supervisor process environment for
  workflow compatibility, strips Python/dynamic-loader/shell startup
  injection variables (``PYTHON*``, ``LD_*``, ``DYLD_*``,
  ``BASH_ENV``, ``ENV``, ``CDPATH``), and sets at least
  ``PYTHONDONTWRITEBYTECODE=1`` and ``PYTHONNOUSERSITE=1``. Ordinary
  toolchain variables such as ``PATH``/``HOME``/Flutter/Android
  variables are preserved.
* **This environment is executor policy but is NOT bound by P2e2a.**
  The supervisor process environment remains trusted input. An
  attacker who can poison the supervisor environment can affect the
  spawned operation step. P2e2a binds only the argv/cwd/timeout/
  primitive/executable identities; it does not bind the environment.

Bounded output and timeout behavior:

* stdout/stderr are fully drained without unbounded memory growth or
  pipe deadlock. SHA-256 and total byte count are computed over the
  complete streams. At most 16 KiB tail per stream is retained in
  memory for the returned report (base64-encoded); truncation is
  marked. Persisted receipts contain only hashes/counts/truncation/
  status.
* On timeout the whole spawned process session/group is killed
  (``SIGKILL`` via ``killpg``), reaped, pipes drained/closed,
  terminal result persisted, and later steps do not run.
* On non-zero/signal/launch error a sanitized terminal result is
  persisted and later steps do not run.

Honest TOCTOU boundary:

* Path verification plus ``subprocess.Popen`` does **not** eliminate
  the verify-to-spawn TOCTOU race for executable/script path
  replacement. The design narrows the window by immediate
  re-verification/re-hashing and exact spawn, but normal path-based
  execution retains a small check-to-exec TOCTOU residual. This
  module does **not** implement a separate OS-specific fd-bound
  execution mechanism that would close that residual; the statement
  above is therefore the truthful boundary.
* The fd-relative receipt claim closes the nonce filename
  symlink/replay race; it does not close executable/script path
  replacement races.

Module I/O boundary (truthful):

* Importing this module performs **no** filesystem I/O, process
  spawn, network access, or write. The installed authorization
  module path is derived purely lexically
  (``Path(os.path.abspath(__file__)).parent``); every
  resolve/lstat/read happens lazily inside ``_load_authorization_module``.
* The module imports ``subprocess`` and ``threading`` because its
  purpose is to spawn the exact authorized argv. It never imports
  ``socket``/``urllib``/``http.client``/``requests`` and never uses
  ``shell=True``, ``os.system``, ``os.popen``, ``os.exec*``,
  ``os.spawn*``, ``os.fork``, ``subprocess.call``/``check_call``/
  ``check_output``/``getoutput``/``getstatusoutput``, or any
  arbitrary-command API. It never deletes, truncates, renames, or
  overwrites a claim or result file. It never persists raw stdout or
  stderr.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import selectors
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Public schema constants.
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1
KIND_REPORT = "icp.flutter-execution-report.v1"
KIND_CLAIM = "icp.flutter-execution-claim.v1"
KIND_RESULT = "icp.flutter-execution-result.v1"
CODE = "flutter_execution_executor_failed"

# Fixed receipt directory name under the verified run root.
RECEIPT_DIRNAME = ".icp-execution-receipts-v1"

# Capped transient tail retained in memory for the returned report.
TAIL_MAX_BYTES = 16 * 1024  # 16 KiB

# Bounded grace period (seconds) used by the single-threaded drain loop
# to wait for a descendant that inherits a pipe fd to terminate after
# the direct child has exited. After this grace the executor kills the
# captured process group and classifies output_drain_failure if the
# pipe is still not at EOF.
_DESCENDANT_GRACE_SECONDS = 5.0

# Poll interval (seconds) for the select-based drain loop.
_DRAIN_POLL_INTERVAL = 0.05

# Receipt file modes (immutable claims/results).
CLAIM_FILE_MODE = 0o600
RESULT_FILE_MODE = 0o600
RECEIPT_DIR_MODE = 0o700

# ---------------------------------------------------------------------------
# Fixed production paths derived from this module's installed location.
# Accepts NO override; this is the runtime surface.
#
# This is a PURELY LEXICAL derivation: ``os.path.abspath`` only collapses
# ``.``/``..`` syntactically and never touches the filesystem. The real
# filesystem-resolution / regular-file / non-symlink integrity checks
# for ``_AUTHZ_PATH`` run lazily inside ``_load_authorization_module``
# (never at import time), so importing this module performs no
# filesystem I/O at all.
# ---------------------------------------------------------------------------

_PLATFORMS_DIR = Path(os.path.abspath(__file__)).parent
_AUTHZ_PATH = _PLATFORMS_DIR / "flutter_execution_authorization_v1.py"

# ---------------------------------------------------------------------------
# Environment policy: strip Python / dynamic-loader / shell startup
# injection variables; preserve ordinary toolchain variables.
#
# TRUTHFUL BOUNDARY: this environment is executor policy but is NOT
# bound by P2e2a. The supervisor process environment remains trusted
# input. P2e2a binds the argv/cwd/timeout/primitive/executable
# identities; it does not bind the environment.
# ---------------------------------------------------------------------------

_ENV_STRIP_PREFIXES: tuple[str, ...] = ("PYTHON", "LD_", "DYLD_")
_ENV_STRIP_EXACT: frozenset[str] = frozenset({"BASH_ENV", "ENV", "CDPATH"})
_ENV_SET: dict[str, str] = {
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONNOUSERSITE": "1",
}


class FlutterExecutionExecutorError(Exception):
    """A local Flutter execution executor failure.

    Raised for any verification/verification-drift/shape/digest/path/
    nonce/replay/launch failure. Generic failures are converted at the
    public API boundary to instances of this class whose message
    exposes the original exception's type name only; arbitrary
    exception text is never leaked."""


class _ClaimExists(Exception):
    """Internal sentinel: the nonce's claim file already exists."""


class _IntegrityError(Exception):
    """Internal sentinel: a pre-spawn executable/primitive/cwd path or
    digest integrity check failed."""


# ---------------------------------------------------------------------------
# Lazy authorization-module loader (no sys.path mutation, no I/O at
# import time).
# ---------------------------------------------------------------------------

_AUTHZ_MODULE: Any = None


def _load_module_by_path(name: str, path: Path):
    try:
        if path.is_symlink():
            raise FlutterExecutionExecutorError(
                f"refusing symlink module: {path}"
            )
        st = path.lstat()
    except OSError as exc:
        raise FlutterExecutionExecutorError(
            f"cannot lstat module {path}: {type(exc).__name__}"
        ) from exc
    if not stat.S_ISREG(st.st_mode):
        raise FlutterExecutionExecutorError(
            f"module not a regular file: {path}"
        )
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise FlutterExecutionExecutorError(
            f"cannot load module spec: {path}"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_authorization_module():
    """Load the shared Flutter execution authorization module.

    Performs the lazy filesystem integrity check that the lexical
    ``_AUTHZ_PATH`` strict-resolves to itself (so a symlinked ancestor
    redirecting the path is rejected), then delegates to
    :func:`_load_module_by_path` for the non-symlink-leaf, regular-
    file and module-spec checks. All filesystem I/O happens here at
    first call, never at import time."""
    global _AUTHZ_MODULE
    if _AUTHZ_MODULE is None:
        try:
            resolved = _AUTHZ_PATH.resolve(strict=True)
        except FileNotFoundError as exc:
            raise FlutterExecutionExecutorError(
                f"authorization module not found: {_AUTHZ_PATH}"
            ) from exc
        except RuntimeError as exc:
            raise FlutterExecutionExecutorError(
                f"authorization module resolve loop: {type(exc).__name__}"
            ) from exc
        except OSError as exc:
            raise FlutterExecutionExecutorError(
                f"authorization module resolve failed: {type(exc).__name__}"
            ) from exc
        if resolved != _AUTHZ_PATH:
            raise FlutterExecutionExecutorError(
                f"authorization module path differs from strict resolve "
                f"(symlinked ancestor): {_AUTHZ_PATH} -> {resolved}"
            )
        _AUTHZ_MODULE = _load_module_by_path(
            "flutter_execution_authorization_v1_p2e2b", _AUTHZ_PATH
        )
    return _AUTHZ_MODULE


# ---------------------------------------------------------------------------
# Canonical JSON / digest helpers.
# ---------------------------------------------------------------------------


def _canonical_compact_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file_bytes(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _is_sha256_hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value.islower()
        and all(c in "0123456789abcdef" for c in value)
    )


# ---------------------------------------------------------------------------
# Public-boundary expected-value validation.
# ---------------------------------------------------------------------------


def _validate_expected_str(name: str, value: Any) -> str:
    if not isinstance(value, str):
        raise FlutterExecutionExecutorError(
            f"{name}: must be a string, got {type(value).__name__}"
        )
    return value


def _validate_expected_sha(name: str, value: Any) -> str:
    if not _is_sha256_hex(value):
        raise FlutterExecutionExecutorError(
            f"{name}: malformed sha256: {value!r}"
        )
    return value


# ---------------------------------------------------------------------------
# Run-root derivation. The run root is derived from the freshly
# verified candidate's embedded selection_verification only; no caller
# override is accepted.
# ---------------------------------------------------------------------------


def _derive_run_root(authorization: dict[str, Any]) -> Path:
    embedded = authorization.get("verified_binding")
    if not isinstance(embedded, dict):
        raise FlutterExecutionExecutorError(
            "verified_binding missing from authorization"
        )
    sel = embedded.get("selection_verification")
    if not isinstance(sel, dict):
        raise FlutterExecutionExecutorError(
            "verified_binding.selection_verification missing"
        )
    run_root_str = sel.get("run_root")
    if not isinstance(run_root_str, str):
        raise FlutterExecutionExecutorError(
            "verified_binding.selection_verification.run_root must be a string"
        )
    manifest_path = authorization.get("selection_manifest_path")
    if not isinstance(manifest_path, str):
        raise FlutterExecutionExecutorError(
            "authorization.selection_manifest_path must be a string"
        )
    if Path(manifest_path).parent != Path(run_root_str):
        raise FlutterExecutionExecutorError(
            "selection_manifest_path.parent != verified run_root"
        )
    return Path(run_root_str)


# ---------------------------------------------------------------------------
# Receipt directory open (relative to a run-root directory fd).
#
# Open the run root with O_NOFOLLOW | O_CLOEXEC where supported (so a
# symlink at the run-root path is rejected). Open or create the fixed
# receipt directory relative to that fd; reject if it is a symlink,
# non-directory, owned by another uid, or has permissions broader than
# 0700.
# ---------------------------------------------------------------------------


def _directory_open_flags() -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    return flags


def _check_dir_owner_mode(
    fd: int, role: str, *, exact_perm: int | None, max_perm: int | None = None
) -> None:
    """Verify a directory fd is a directory owned by the current uid
    with acceptable permissions.

    Permission semantics (applied in order):

    * ``exact_perm`` (int, e.g. ``0o700``): on-disk permission bits
      must equal this value exactly. Used for a freshly created
      receipt directory.
    * ``max_perm`` (int, e.g. ``0o700``): on-disk permission bits may
      be this value or stricter (existing dirs). Mutually exclusive
      with ``exact_perm``.
    * Neither set: any permission bits are accepted (the run root is
      not mode-restricted by this contract; only its owner must match
      so a foreign-owned run root cannot host a receipt directory)."""
    try:
        st = os.fstat(fd)
    except OSError as exc:
        raise FlutterExecutionExecutorError(
            f"{role}: cannot fstat: {type(exc).__name__}"
        ) from exc
    if not stat.S_ISDIR(st.st_mode):
        raise FlutterExecutionExecutorError(f"{role}: not a directory")
    if hasattr(os, "geteuid"):
        if st.st_uid != os.geteuid():
            raise FlutterExecutionExecutorError(
                f"{role}: not owned by current uid "
                f"(got {st.st_uid}, expected {os.geteuid()})"
            )
    perm = stat.S_IMODE(st.st_mode)
    if exact_perm is not None:
        if perm != exact_perm:
            raise FlutterExecutionExecutorError(
                f"{role}: permissions not exactly {oct(exact_perm)}: "
                f"{oct(perm)}"
            )
    elif max_perm is not None:
        if perm & ~max_perm:
            raise FlutterExecutionExecutorError(
                f"{role}: permissions too broad: {oct(perm)} "
                f"(maximum allowed {oct(max_perm)})"
            )


def _open_run_root_fd(run_root: Path) -> int:
    """Open the run root as a directory fd. Reject symlinks at the
    lexical path (O_NOFOLLOW), non-directories, and wrong owner."""
    flags = _directory_open_flags()
    try:
        fd = os.open(str(run_root), flags)
    except FileNotFoundError as exc:
        raise FlutterExecutionExecutorError(
            f"run_root not found: {run_root}"
        ) from exc
    except OSError as exc:
        raise FlutterExecutionExecutorError(
            f"cannot open run_root {run_root}: {type(exc).__name__}"
        ) from exc
    try:
        _check_dir_owner_mode(fd, "run_root", exact_perm=None)
    except FlutterExecutionExecutorError:
        try:
            os.close(fd)
        finally:
            pass
        raise
    return fd


def _open_or_create_receipt_dir(run_root_fd: int) -> int:
    """Open or create the fixed receipt directory relative to
    ``run_root_fd``.

    A freshly created directory is forced to mode exactly ``0700`` via
    ``fchmod(fd, 0700)`` (the mkdir mode is masked by the caller's
    process umask; fchmod is authoritative) and verified with ``fstat``
    to be exactly ``0700``. This routine never calls ``os.umask``: the
    process umask is global state and would race concurrent callers.
    An existing directory must be owned by the current uid with
    permissions no broader than ``0700`` (it may be stricter, e.g.
    ``0500``). Symlink/non-directory/wrong-owner are rejected in both
    cases."""
    name = RECEIPT_DIRNAME
    is_new = False
    try:
        os.mkdir(name, dir_fd=run_root_fd, mode=RECEIPT_DIR_MODE)
        is_new = True
    except FileExistsError:
        pass
    except OSError as exc:
        raise FlutterExecutionExecutorError(
            f"cannot create receipt dir: {type(exc).__name__}"
        ) from exc
    flags = _directory_open_flags()
    try:
        fd = os.open(name, flags, dir_fd=run_root_fd)
    except OSError as exc:
        raise FlutterExecutionExecutorError(
            f"cannot open receipt dir: {type(exc).__name__}"
        ) from exc
    try:
        if is_new:
            # Force exact 0700 on a freshly created directory. The
            # mkdir mode argument is masked by the caller's process
            # umask; fchmod is authoritative and does not touch umask.
            try:
                os.fchmod(fd, RECEIPT_DIR_MODE)
            except OSError as exc:
                raise FlutterExecutionExecutorError(
                    f"receipt_dir: cannot fchmod: {type(exc).__name__}"
                ) from exc
            _check_dir_owner_mode(
                fd, "receipt_dir", exact_perm=RECEIPT_DIR_MODE
            )
        else:
            _check_dir_owner_mode(
                fd, "receipt_dir", exact_perm=None, max_perm=RECEIPT_DIR_MODE
            )
    except FlutterExecutionExecutorError:
        try:
            os.close(fd)
        finally:
            pass
        raise
    return fd


# ---------------------------------------------------------------------------
# Atomic claim and result writers (relative to a receipt-directory fd).
# Never delete, truncate, rename, or overwrite a claim or result.
# ---------------------------------------------------------------------------


def _open_excl_relative(receipt_fd: int, name: str, mode: int) -> int:
    """Open ``name`` relative to ``receipt_fd`` with
    ``O_CREAT | O_EXCL | O_WRONLY`` (plus ``O_NOFOLLOW | O_CLOEXEC``
    where supported) and mode ``mode``.

    Raises :class:`_ClaimExists` on ``FileExistsError`` so the caller
    can classify replay. Raises :class:`FlutterExecutionExecutorError`
    on other OSError."""
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        return os.open(name, flags, mode, dir_fd=receipt_fd)
    except FileExistsError as exc:
        raise _ClaimExists() from exc
    except OSError as exc:
        raise FlutterExecutionExecutorError(
            f"cannot create {name}: {type(exc).__name__}"
        ) from exc


def _verify_file_mode(fd: int, expected: int, role: str) -> None:
    """Verify the open file ``fd`` is a regular file with exactly the
    expected permission bits. Used to guarantee newly created claim and
    result files are exactly ``0600`` (filesystems may narrow the mode
    passed to :func:`os.open`)."""
    try:
        st = os.fstat(fd)
    except OSError as exc:
        raise FlutterExecutionExecutorError(
            f"{role}: cannot fstat: {type(exc).__name__}"
        ) from exc
    if not stat.S_ISREG(st.st_mode):
        raise FlutterExecutionExecutorError(f"{role}: not a regular file")
    perm = stat.S_IMODE(st.st_mode)
    if perm != expected:
        raise FlutterExecutionExecutorError(
            f"{role}: mode not exactly {oct(expected)}: {oct(perm)}"
        )


def _write_all_fd(fd: int, data: bytes, role: str) -> None:
    """Write all of ``data`` to ``fd``; raise on partial-write stall.
    On any BaseException the file is closed but NEVER deleted or
    truncated: a partially-written claim still consumes the nonce
    forever."""
    written = 0
    try:
        while written < len(data):
            try:
                n = os.write(fd, data[written:])
            except BlockingIOError as exc:  # pragma: no cover - defensive
                raise FlutterExecutionExecutorError(
                    f"{role}: blocking write: {type(exc).__name__}"
                ) from exc
            if n <= 0:
                raise FlutterExecutionExecutorError(
                    f"{role}: write returned {n}"
                )
            written += n
        os.fsync(fd)
    except BaseException:
        try:
            os.close(fd)
        finally:
            pass
        raise


def _fsync_dir(dir_fd: int) -> None:
    try:
        os.fsync(dir_fd)
    except OSError:
        # Fsync on directories is not supported on every filesystem;
        # the failure is not fatal to durability on local filesystems
        # that order metadata writes.
        pass


def _atomic_claim_nonce(
    receipt_fd: int, claim_filename: str, claim_payload: dict[str, Any]
) -> str:
    """Atomically create the claim file relative to ``receipt_fd`` and
    return the claim_digest. Raises :class:`_ClaimExists` if the file
    already exists. The new claim file is forced to exactly mode
    ``0600`` (via ``fchmod``) and verified with ``fstat`` before any
    data is written; fsync(file) and fsync(dir) follow."""
    payload_no_digest = {
        k: v for k, v in claim_payload.items() if k != "claim_digest"
    }
    claim_digest = _sha256_bytes(_canonical_compact_bytes(payload_no_digest))
    claim_payload["claim_digest"] = claim_digest
    fd = _open_excl_relative(receipt_fd, claim_filename, CLAIM_FILE_MODE)
    try:
        os.fchmod(fd, CLAIM_FILE_MODE)
        _verify_file_mode(fd, CLAIM_FILE_MODE, "claim")
    except OSError as exc:
        try:
            os.close(fd)
        finally:
            pass
        raise FlutterExecutionExecutorError(
            f"claim: cannot fchmod: {type(exc).__name__}"
        ) from exc
    except FlutterExecutionExecutorError:
        try:
            os.close(fd)
        finally:
            pass
        raise
    data = _canonical_compact_bytes(claim_payload)
    _write_all_fd(fd, data, "claim")
    os.close(fd)
    _fsync_dir(receipt_fd)
    return claim_digest


def _atomic_write_result(
    receipt_fd: int, result_filename: str, result_payload: dict[str, Any]
) -> str:
    """Atomically create the result file relative to ``receipt_fd`` and
    return the result_digest. If the file already exists, raises
    :class:`FlutterExecutionExecutorError` (the caller treats this as a
    crash-race and surfaces a non-success report). The new result file
    is forced to exactly mode ``0600`` (via ``fchmod``) and verified
    with ``fstat`` before any data is written; fsync(file) and
    fsync(dir) follow. Only the call that owns the claim may call
    this; replay losers must never reach this path."""
    payload_no_digest = {
        k: v for k, v in result_payload.items() if k != "result_digest"
    }
    result_digest = _sha256_bytes(_canonical_compact_bytes(payload_no_digest))
    result_payload["result_digest"] = result_digest
    try:
        fd = _open_excl_relative(receipt_fd, result_filename, RESULT_FILE_MODE)
    except _ClaimExists as exc:
        raise FlutterExecutionExecutorError(
            f"result file already exists: {result_filename}"
        ) from exc
    try:
        os.fchmod(fd, RESULT_FILE_MODE)
        _verify_file_mode(fd, RESULT_FILE_MODE, "result")
    except OSError as exc:
        try:
            os.close(fd)
        finally:
            pass
        raise FlutterExecutionExecutorError(
            f"result: cannot fchmod: {type(exc).__name__}"
        ) from exc
    except FlutterExecutionExecutorError:
        try:
            os.close(fd)
        finally:
            pass
        raise
    data = _canonical_compact_bytes(result_payload)
    _write_all_fd(fd, data, "result")
    os.close(fd)
    _fsync_dir(receipt_fd)
    return result_digest


def _result_file_exists(receipt_fd: int, result_filename: str) -> bool:
    try:
        os.fstatat(receipt_fd, result_filename, os.O_NOFOLLOW)
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return True


# ---------------------------------------------------------------------------
# Payload builders.
# ---------------------------------------------------------------------------


def _build_claim_payload(
    authorization: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    return {
        "kind": KIND_CLAIM,
        "schema_version": SCHEMA_VERSION,
        "execution_nonce": authorization["execution_nonce"],
        "expected_authorization_digest": expected["expected_authorization_digest"],
        "binding_digest": expected["expected_binding_digest"],
        "selection_manifest_path": expected["expected_manifest_path"],
        "selection_manifest_sha256": expected["expected_manifest_sha256"],
        "platform_id": authorization["platform_id"],
        "profile_id": authorization["profile_id"],
        "operation_id": authorization["operation_id"],
        "port_id": authorization["port_id"],
        "step_authorization_digests": [
            sa["step_authorization_digest"]
            for sa in authorization["step_authorizations"]
        ],
    }


def _build_result_payload(
    overall_status: str,
    nonce: str,
    claim_digest: str,
    expected_authorization_digest: str,
    step_results_persist: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the canonical result payload (without result_digest).
    Contains ONLY sanitized execution metadata; never raw/tail output,
    never timestamps, PIDs, hostnames, or random values."""
    return {
        "kind": KIND_RESULT,
        "schema_version": SCHEMA_VERSION,
        "execution_nonce": nonce,
        "claim_digest": claim_digest,
        "expected_authorization_digest": expected_authorization_digest,
        "overall_status": overall_status,
        "step_results": step_results_persist,
    }


# ---------------------------------------------------------------------------
# Executor-owned environment builder.
# ---------------------------------------------------------------------------


def _build_spawn_environment() -> dict[str, str]:
    """Build the executor-owned spawn environment from the trusted
    supervisor process environment. Strips Python/dynamic-loader/
    shell startup injection variables and sets
    ``PYTHONDONTWRITEBYTECODE=1`` and ``PYTHONNOUSERSITE=1``. Ordinary
    toolchain variables such as ``PATH``/``HOME``/Flutter/Android
    variables are preserved.

    TRUTHFUL BOUNDARY: this environment is executor policy but is NOT
    bound by P2e2a. The supervisor process environment remains
    trusted input."""
    env: dict[str, str] = {}
    for k, v in os.environ.items():
        if any(k.startswith(p) for p in _ENV_STRIP_PREFIXES):
            continue
        if k in _ENV_STRIP_EXACT:
            continue
        env[k] = v
    env.update(_ENV_SET)
    return env


# ---------------------------------------------------------------------------
# Pre-spawn recheck (defence-in-depth TOCTOU narrow).
# ---------------------------------------------------------------------------


def _pre_spawn_recheck(
    *,
    argv0: str,
    primitive_path: str,
    primitive_sha256: str,
    executable_path: str,
    executable_sha256: str,
    cwd: str,
) -> None:
    """Re-check argv[0]/executable/primitive/cwd immediately before
    spawn. Raises :class:`_IntegrityError` on any mismatch.

    ``argv0`` is the actual first element of the immutable argv tuple
    built from the embedded binding plan step. It must equal
    ``sys.executable`` exactly (the lexical Homebrew interpreter
    symlink is the deliberate, authorized exception).

    The canonical executable target, primitive script, and cwd are
    re-resolved and re-hashed against the authorized values:

    * ``argv[0] == sys.executable`` lexically;
    * ``realpath(sys.executable)`` equals the authorized
      ``executable_path``; the canonical target is a non-symlink
      regular file; its SHA-256 equals ``executable_sha256``;
    * ``primitive_path`` is absolute/normalized, leaf non-symlink
      regular, ``resolve(strict=True)`` equals the lexical bound path,
      SHA matches;
    * ``cwd`` is absolute/normalized, leaf non-symlink directory,
      ``resolve(strict=True)`` equals the lexical bound path."""
    # 1. argv[0] lexical equality with sys.executable.
    if not isinstance(argv0, str) or not argv0:
        raise _IntegrityError("argv[0] not a non-empty string")
    if argv0 != sys.executable:
        raise _IntegrityError("argv[0] lexical mismatch at spawn time")

    # 2. Executable canonical realpath target, regular-file, SHA-256.
    if not isinstance(executable_path, str) or not executable_path:
        raise _IntegrityError("executable_path not a non-empty string")
    exe_real = os.path.realpath(sys.executable)
    if exe_real != executable_path:
        raise _IntegrityError("argv[0] canonical realpath mismatch at spawn time")
    try:
        exe_lstat = os.lstat(exe_real)
    except OSError as exc:
        raise _IntegrityError(
            f"argv[0] lstat failed: {type(exc).__name__}"
        ) from exc
    if stat.S_ISLNK(exe_lstat.st_mode):
        raise _IntegrityError("argv[0] canonical target is a symlink")
    if not stat.S_ISREG(exe_lstat.st_mode):
        raise _IntegrityError("argv[0] not a regular file")
    try:
        exe_actual_sha = _sha256_file_bytes(exe_real)
    except OSError as exc:
        raise _IntegrityError(
            f"argv[0] unreadable: {type(exc).__name__}"
        ) from exc
    if exe_actual_sha != executable_sha256:
        raise _IntegrityError("argv[0] sha drift at spawn time")

    # 3. Primitive: absolute/normalized; leaf non-symlink regular;
    #    strict canonical resolve equals the lexical bound path; SHA
    #    matches.
    if not isinstance(primitive_path, str) or not primitive_path:
        raise _IntegrityError("primitive_path not a non-empty string")
    _require_canonical_lexical(primitive_path, "primitive_path")
    try:
        if os.path.islink(primitive_path):
            raise _IntegrityError("primitive leaf is a symlink")
        prim_lstat = os.lstat(primitive_path)
    except OSError as exc:
        raise _IntegrityError(
            f"primitive lstat failed: {type(exc).__name__}"
        ) from exc
    if not stat.S_ISREG(prim_lstat.st_mode):
        raise _IntegrityError("primitive not a regular file")
    _require_strict_resolve(primitive_path, "primitive_path")
    try:
        prim_actual_sha = _sha256_file_bytes(primitive_path)
    except OSError as exc:
        raise _IntegrityError(
            f"primitive unreadable: {type(exc).__name__}"
        ) from exc
    if prim_actual_sha != primitive_sha256:
        raise _IntegrityError("primitive sha drift at spawn time")

    # 4. cwd: absolute/normalized; leaf non-symlink directory; strict
    #    canonical resolve equals the lexical bound path.
    if not isinstance(cwd, str) or not cwd:
        raise _IntegrityError("cwd not a non-empty string")
    _require_canonical_lexical(cwd, "cwd")
    try:
        if os.path.islink(cwd):
            raise _IntegrityError("cwd leaf is a symlink")
        cwd_lstat = os.lstat(cwd)
    except OSError as exc:
        raise _IntegrityError(
            f"cwd lstat failed: {type(exc).__name__}"
        ) from exc
    if not stat.S_ISDIR(cwd_lstat.st_mode):
        raise _IntegrityError("cwd not a directory")
    _require_strict_resolve(cwd, "cwd")


def _require_canonical_lexical(path: str, role: str) -> None:
    if not os.path.isabs(path):
        raise _IntegrityError(f"{role}: not absolute")
    if any(part == ".." for part in Path(path).parts):
        raise _IntegrityError(f"{role}: contains '..'")
    if os.path.normpath(path) != path:
        raise _IntegrityError(f"{role}: not lexically normalized")


def _require_strict_resolve(path: str, role: str) -> None:
    """Require ``Path(path).resolve(strict=True)`` equals the lexical
    ``path``. This rejects any symlink anywhere along the resolution
    chain (including macOS ``/var`` -> ``/private/var`` ancestor
    symlinks that would otherwise survive a leaf lstat check)."""
    try:
        resolved = Path(path).resolve(strict=True)
    except FileNotFoundError as exc:
        raise _IntegrityError(f"{role}: strict resolve not found") from exc
    except RuntimeError as exc:
        raise _IntegrityError(
            f"{role}: strict resolve loop: {type(exc).__name__}"
        ) from exc
    except OSError as exc:
        raise _IntegrityError(
            f"{role}: strict resolve failed: {type(exc).__name__}"
        ) from exc
    if str(resolved) != path:
        raise _IntegrityError(
            f"{role}: lexical path != strict canonical resolve "
            f"({path} -> {resolved})"
        )


# ---------------------------------------------------------------------------
# Bounded single-threaded stream drain. Uses ``selectors`` to drain
# stdout and stderr concurrently without spawning any reader thread.
# Computes SHA-256 and byte count over the full streams; retains at
# most TAIL_MAX_BYTES tail per stream in memory.
#
# Invariant: when ``_spawn_step`` returns or raises, it has NO
# executor-owned live reader thread (there is none by construction)
# and NO live child process in the spawned group.
# ---------------------------------------------------------------------------


class _StreamAccumulator:
    """Per-stream byte counter, SHA-256 hasher, and bounded tail. No
    thread state; purely an in-memory accumulator mutated by the
    single-threaded drain loop."""

    __slots__ = ("_hasher", "_count", "_tail", "read_error", "eof")

    def __init__(self) -> None:
        self._hasher = hashlib.sha256()
        self._count = 0
        self._tail = bytearray()
        self.read_error: str | None = None
        self.eof = False

    def feed(self, chunk: bytes) -> None:
        if not chunk:
            self.eof = True
            return
        self._hasher.update(chunk)
        self._count += len(chunk)
        self._tail.extend(chunk)
        if len(self._tail) > TAIL_MAX_BYTES * 2:
            del self._tail[: len(self._tail) - TAIL_MAX_BYTES]

    def fail(self, exc_cls: str) -> None:
        self.read_error = exc_cls

    def finish(self) -> dict[str, Any]:
        if len(self._tail) > TAIL_MAX_BYTES:
            del self._tail[: len(self._tail) - TAIL_MAX_BYTES]
        return {
            "byte_count": self._count,
            "sha256": self._hasher.hexdigest(),
            "tail": bytes(self._tail),
            "truncated": self._count > TAIL_MAX_BYTES,
            "read_error": self.read_error,
        }


def _effective_timeout(timeout_seconds: int) -> int:
    """Return the effective spawn timeout. Production callers pass the
    bound ``timeout_seconds`` directly; the indirection exists as a
    narrowly scoped test seam so selftests can drive the timeout path
    without waiting for the full bound timeout."""
    return timeout_seconds


def _set_nonblock(fd: int) -> None:
    """Set ``fd`` to non-blocking mode using the standard
    :func:`os.set_blocking` helper. Equivalent to ``fcntl`` F_SETFL
    with ``O_NONBLOCK`` but portable and does not require importing
    the platform-specific ``fcntl`` module."""
    os.set_blocking(fd, False)


def _read_pipe_chunk(fd: int) -> bytes:
    """Read one chunk from a non-blocking pipe fd. Narrow indirection
    so fault-injection tests can drive the read-error path without
    patching the global :func:`os.read`."""
    return os.read(fd, 65536)


def _kill_pgid(pgid: int) -> None:
    """Kill the exact process group id with SIGKILL. Never raises.
    Using the captured pgid (not os.getpgid(proc.pid)) means this
    reaches descendants in the original group even after the session
    leader has exited."""
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, OSError):
        pass


def _reap_child(proc: subprocess.Popen, timeout: float = 5.0) -> None:
    """Best-effort reap the direct child. Never raises."""
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        pass
    except OSError:
        pass


def _drain_best_effort(
    sel: selectors.BaseSelector,
    stdout_acc: _StreamAccumulator,
    stderr_acc: _StreamAccumulator,
) -> None:
    """After killing the group on a drain failure, make a short
    best-effort pass to drain any immediately-readable bytes so the
    reported byte count and hash reflect what was actually captured.
    Any further read error marks the accumulator failed. Selector or
    read errors here are swallowed so the caller's
    ``output_drain_failure`` classification is retained rather than
    propagating as ``internal_error``."""
    deadline = time.monotonic() + 0.5
    while time.monotonic() < deadline:
        try:
            ready = sel.select(timeout=0.05)
        except (OSError, ValueError):
            # Best-effort selector failure: stop draining silently.
            break
        if not ready:
            break
        for key, _mask in ready:
            acc: _StreamAccumulator = key.data
            fd = key.fd
            try:
                chunk = _read_pipe_chunk(fd)
            except BlockingIOError:
                continue
            except OSError as exc:
                acc.fail(type(exc).__name__)
                acc.eof = True
                try:
                    sel.unregister(fd)
                except (KeyError, ValueError):
                    pass
                continue
            if not chunk:
                acc.eof = True
                try:
                    sel.unregister(fd)
                except (KeyError, ValueError):
                    pass
            else:
                acc.feed(chunk)
        if stdout_acc.eof and stderr_acc.eof:
            break


def _spawn_step(
    *,
    argv_tuple: tuple[str, ...],
    cwd: str,
    timeout_seconds: int,
    env: dict[str, str],
) -> dict[str, Any]:
    """Spawn the argv tuple. Returns a step result dict.

    The drain loop is single-threaded (``selectors``) so by
    construction there is never an executor-owned live reader thread
    when this function returns or raises. On timeout or output-drain
    failure the captured process group is killed with ``SIGKILL`` and
    the direct child is reaped.

    Bounded behaviour if descendants keep pipe fds open after the
    direct child exits: the loop waits at most
    ``_DESCENDANT_GRACE_SECONDS`` after the child exits for both pipes
    to reach EOF. If after that grace a pipe is still not at EOF the
    process group is killed, the pipes are drained best-effort, and
    the step is classified ``output_drain_failure``.

    Cleanup invariant: immediately after a successful ``Popen`` the
    captured ``pgid=proc.pid`` and the pipe objects are tracked so
    that any post-Popen failure is covered by a single outer
    ``try/finally`` that always kills the captured pgid, reaps the
    direct child, closes the selector if constructed, and closes both
    pipe objects if present. No process/group/fd leak on any path.

    Failure classification contract:

    * ``Popen`` failure and post-Popen ``OSError`` setup failure
      (``_set_nonblock``, selector construction/registration) surface
      to the caller's sanitized ``launch_error`` contract.
    * Handled selector ``select()`` / pipe-read / descendant-grace /
      best-effort drain failures are returned in-band as
      ``output_drain_failure`` (never propagated as
      ``internal_error``).
    * Unexpected non-``OSError`` exceptions propagate to the existing
      terminal internal-error boundary in ``_run_with_receipts``,
      which persists a sanitized ``internal_error`` terminal result
      owned by the claimant."""
    proc = subprocess.Popen(
        list(argv_tuple),
        shell=False,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
        start_new_session=True,
        env=env,
    )
    # Capture the process group id immediately: with
    # start_new_session=True the child is the session/group leader so
    # its pgid is its own pid. Killing this exact pgid reaches
    # descendants even after the leader has exited.
    pgid = proc.pid
    sel: selectors.BaseSelector | None = None
    stdout_acc = _StreamAccumulator()
    stderr_acc = _StreamAccumulator()
    timed_out = False
    grace_drain_forced = False
    deadline: float | None = None
    if timeout_seconds is not None and timeout_seconds > 0:
        deadline = time.monotonic() + float(timeout_seconds)

    try:
        stdout_fd = proc.stdout.fileno()
        stderr_fd = proc.stderr.fileno()
        _set_nonblock(stdout_fd)
        _set_nonblock(stderr_fd)
        sel = selectors.DefaultSelector()
        sel.register(stdout_fd, selectors.EVENT_READ, stdout_acc)
        sel.register(stderr_fd, selectors.EVENT_READ, stderr_acc)
        child_exited = False
        descendant_grace_deadline: float | None = None
        while True:
            # Determine the select timeout.
            timeouts: list[float] = []
            if deadline is not None:
                timeouts.append(max(0.0, deadline - time.monotonic()))
            if descendant_grace_deadline is not None:
                timeouts.append(
                    max(0.0, descendant_grace_deadline - time.monotonic())
                )
            if not timeouts:
                select_timeout = _DRAIN_POLL_INTERVAL
            else:
                select_timeout = min(min(timeouts), _DRAIN_POLL_INTERVAL)

            try:
                ready = sel.select(timeout=select_timeout)
            except (OSError, ValueError) as exc:
                # Selector failure is an output drain failure: record
                # a sanitized error class, kill the captured process
                # group, reap the child, and break out of the drain
                # loop promptly. Do NOT silently swallow the failure
                # and spin until the operation timeout.
                stdout_acc.fail(type(exc).__name__)
                _kill_pgid(pgid)
                _reap_child(proc)
                grace_drain_forced = True
                break
            for key, _mask in ready:
                acc: _StreamAccumulator = key.data
                fd = key.fd
                try:
                    chunk = _read_pipe_chunk(fd)
                except BlockingIOError:
                    continue
                except OSError as exc:
                    acc.fail(type(exc).__name__)
                    _kill_pgid(pgid)
                    _reap_child(proc)
                    acc.eof = True
                    grace_drain_forced = True
                    try:
                        sel.unregister(fd)
                    except (KeyError, ValueError):
                        pass
                    continue
                if not chunk:
                    acc.eof = True
                    try:
                        sel.unregister(fd)
                    except (KeyError, ValueError):
                        pass
                else:
                    acc.feed(chunk)

            if stdout_acc.eof and stderr_acc.eof:
                break

            if not child_exited and deadline is not None:
                if time.monotonic() >= deadline:
                    timed_out = True
                    _kill_pgid(pgid)
                    _reap_child(proc)
                    child_exited = True
                    descendant_grace_deadline = (
                        time.monotonic() + _DESCENDANT_GRACE_SECONDS
                    )

            if not child_exited:
                rc = proc.poll()
                if rc is not None:
                    child_exited = True
                    descendant_grace_deadline = (
                        time.monotonic() + _DESCENDANT_GRACE_SECONDS
                    )
                elif deadline is not None and time.monotonic() >= deadline:
                    timed_out = True
                    _kill_pgid(pgid)
                    _reap_child(proc)
                    child_exited = True
                    descendant_grace_deadline = (
                        time.monotonic() + _DESCENDANT_GRACE_SECONDS
                    )

            if child_exited:
                if stdout_acc.eof and stderr_acc.eof:
                    break
                if (
                    descendant_grace_deadline is not None
                    and time.monotonic() >= descendant_grace_deadline
                ):
                    # A descendant held the pipe past the grace window.
                    # Kill the original group and mark this as a forced
                    # drain failure (not a clean EOF).
                    _kill_pgid(pgid)
                    _reap_child(proc)
                    _drain_best_effort(sel, stdout_acc, stderr_acc)
                    grace_drain_forced = True
                    break
    finally:
        # Always: kill the captured exact pgid, reap the direct child,
        # close the selector if constructed, close both pipe objects if
        # present. This single finally covers every path: normal
        # completion, timeout, in-band output_drain_failure, and setup
        # failure that raised out of the try block (the caller then
        # classifies OSError as launch_error, or propagates unexpected
        # exceptions to the terminal internal-error boundary).
        if sel is not None:
            try:
                sel.close()
            except Exception:  # noqa: BLE001
                pass
        _kill_pgid(pgid)
        _reap_child(proc)
        if proc.stdout is not None:
            try:
                proc.stdout.close()
            except OSError:
                pass
        if proc.stderr is not None:
            try:
                proc.stderr.close()
            except OSError:
                pass

    stdout_info = stdout_acc.finish()
    stderr_info = stderr_acc.finish()
    drain_failed = (
        grace_drain_forced
        or stdout_info["read_error"] is not None
        or stderr_info["read_error"] is not None
        or (not stdout_acc.eof)
        or (not stderr_acc.eof)
    )

    if drain_failed:
        status = "output_drain_failure"
        exit_code: Any = proc.returncode
        signal_number: Any = None
    elif timed_out:
        status = "timed_out"
        exit_code = None
        signal_number = None
    else:
        rc = proc.returncode
        if rc is None:
            status = "launch_error"
            exit_code = None
            signal_number = None
        elif rc < 0:
            status = "signal"
            exit_code = None
            signal_number = -rc
        elif rc == 0:
            status = "success"
            exit_code = 0
            signal_number = None
        else:
            status = "non_zero_exit"
            exit_code = rc
            signal_number = None

    return {
        "status": status,
        "exit_code": exit_code,
        "signal_number": signal_number,
        "stdout_byte_count": stdout_info["byte_count"],
        "stdout_sha256": stdout_info["sha256"],
        "stdout_tail_b64": base64.b64encode(stdout_info["tail"]).decode("ascii"),
        "stdout_truncated": stdout_info["truncated"],
        "stderr_byte_count": stderr_info["byte_count"],
        "stderr_sha256": stderr_info["sha256"],
        "stderr_tail_b64": base64.b64encode(stderr_info["tail"]).decode("ascii"),
        "stderr_truncated": stderr_info["truncated"],
    }


# ---------------------------------------------------------------------------
# Step validation: argv tuple build + plan-step vs step-authorization
# equality.
# ---------------------------------------------------------------------------


def _build_argv_tuple(step: dict[str, Any]) -> tuple[str, ...]:
    argv = step.get("argv")
    if not isinstance(argv, list):
        raise _IntegrityError("step.argv not a list")
    if len(argv) < 2:
        raise _IntegrityError("step.argv has fewer than 2 elements")
    out: list[str] = []
    for elem in argv:
        if not isinstance(elem, str):
            raise _IntegrityError("step.argv element not a string")
        if "\x00" in elem:
            raise _IntegrityError("step.argv element contains NUL")
        out.append(elem)
    # argv[0] must equal sys.executable exactly (the lexical Homebrew
    # symlink is valid; canonical realpath identity is checked in
    # _pre_spawn_recheck).
    if out[0] != sys.executable:
        raise _IntegrityError("argv[0] != sys.executable")
    return tuple(out)


def _validate_step_against_step_authz(
    step: dict[str, Any], sa: dict[str, Any], index: int
) -> None:
    """Require exact equality between the embedded binding plan step
    and the same-index step authorization."""
    if step.get("step_id") != sa["step_id"]:
        raise _IntegrityError(f"step[{index}].step_id mismatch")
    if step.get("primitive") != sa["primitive"]:
        raise _IntegrityError(f"step[{index}].primitive mismatch")
    if step.get("primitive_sha256") != sa["primitive_sha256"]:
        raise _IntegrityError(f"step[{index}].primitive_sha256 mismatch")
    if step.get("cwd") != sa["cwd"]:
        raise _IntegrityError(f"step[{index}].cwd mismatch")
    if step.get("timeout_seconds") != sa["timeout_seconds"]:
        raise _IntegrityError(f"step[{index}].timeout_seconds mismatch")
    argv = step.get("argv")
    if not isinstance(argv, list):
        raise _IntegrityError(f"step[{index}].argv not a list")
    expected_argv_digest = _sha256_bytes(_canonical_compact_bytes(argv))
    if expected_argv_digest != sa["argv_digest"]:
        raise _IntegrityError(f"step[{index}].argv digest mismatch")
    if len(argv) >= 2:
        if sa["primitive_path"] != os.path.realpath(argv[1]):
            raise _IntegrityError(
                f"step[{index}].primitive_path != argv[1] canonical"
            )
    if len(argv) >= 1:
        if sa["executable_path"] != os.path.realpath(argv[0]):
            raise _IntegrityError(
                f"step[{index}].executable_path != argv[0] canonical"
            )


# ---------------------------------------------------------------------------
# Skipped-step markers.
# ---------------------------------------------------------------------------


def _mark_skipped(
    start: int,
    plan_steps: list[dict[str, Any]],
    report_list: list[dict[str, Any]],
    persist_list: list[dict[str, Any]],
) -> None:
    for j in range(start, len(plan_steps)):
        report_list.append(
            {
                "step_index": j,
                "step_id": plan_steps[j]["step_id"],
                "status": "skipped",
            }
        )
        persist_list.append(
            {
                "step_index": j,
                "step_id": plan_steps[j]["step_id"],
                "status": "skipped",
            }
        )


# ---------------------------------------------------------------------------
# execute_authorization implementation.
# ---------------------------------------------------------------------------


def _execute_impl(
    authorization: Any,
    *,
    expected_manifest_path: Any,
    expected_manifest_sha256: Any,
    expected_binding_digest: Any,
    expected_authorization_digest: Any,
) -> dict[str, Any]:
    if not isinstance(authorization, dict):
        raise FlutterExecutionExecutorError(
            f"authorization must be a dict, got {type(authorization).__name__}"
        )

    # 1. Validate every trusted-supplied expected value. None may
    #    default, be inferred from the untrusted document, or be
    #    optional.
    exp_manifest_path = _validate_expected_str(
        "expected_manifest_path", expected_manifest_path
    )
    exp_manifest_sha = _validate_expected_sha(
        "expected_manifest_sha256", expected_manifest_sha256
    )
    exp_binding_digest = _validate_expected_sha(
        "expected_binding_digest", expected_binding_digest
    )
    exp_authz_digest = _validate_expected_sha(
        "expected_authorization_digest", expected_authorization_digest
    )

    authz_module = _load_authorization_module()

    # 2. Pre-claim verification. Fail closed before any receipt is
    #    written. This re-runs the fixed transitive Flutter version
    #    preflight subprocess owned by the preflight module.
    verify_report = authz_module.verify_authorization(
        authorization,
        expected_manifest_path=exp_manifest_path,
        expected_manifest_sha256=exp_manifest_sha,
        expected_binding_digest=exp_binding_digest,
        expected_authorization_digest=exp_authz_digest,
    )
    # Cross-check the verification report's identity fields.
    if verify_report["execution_nonce"] != authorization["execution_nonce"]:
        raise FlutterExecutionExecutorError(
            "verify_report execution_nonce != authorization.execution_nonce"
        )
    if verify_report["binding_digest"] != exp_binding_digest:
        raise FlutterExecutionExecutorError(
            "verify_report binding_digest != expected_binding_digest"
        )
    if (
        verify_report["selection_manifest_sha256"]
        != authorization["selection_manifest_sha256"]
    ):
        raise FlutterExecutionExecutorError(
            "verify_report manifest sha != authorization manifest sha"
        )
    if verify_report["authorization_digest"] != exp_authz_digest:
        raise FlutterExecutionExecutorError(
            "verify_report authorization_digest != "
            "expected_authorization_digest"
        )

    # 3. Derive run root from the freshly verified candidate.
    run_root = _derive_run_root(authorization)

    # 4. Open run root and receipt directory fds.
    run_root_fd = _open_run_root_fd(run_root)
    try:
        receipt_fd = _open_or_create_receipt_dir(run_root_fd)
    finally:
        os.close(run_root_fd)

    try:
        return _run_with_receipts(
            receipt_fd=receipt_fd,
            authorization=authorization,
            authz_module=authz_module,
            exp_manifest_path=exp_manifest_path,
            exp_manifest_sha=exp_manifest_sha,
            exp_binding_digest=exp_binding_digest,
            exp_authz_digest=exp_authz_digest,
        )
    finally:
        try:
            os.close(receipt_fd)
        finally:
            pass


def _run_with_receipts(
    *,
    receipt_fd: int,
    authorization: dict[str, Any],
    authz_module: Any,
    exp_manifest_path: str,
    exp_manifest_sha: str,
    exp_binding_digest: str,
    exp_authz_digest: str,
) -> dict[str, Any]:
    nonce = authorization["execution_nonce"]
    claim_filename = f"{nonce}.claim.json"
    result_filename = f"{nonce}.result.json"

    claim_payload = _build_claim_payload(
        authorization,
        {
            "expected_manifest_path": exp_manifest_path,
            "expected_manifest_sha256": exp_manifest_sha,
            "expected_binding_digest": exp_binding_digest,
            "expected_authorization_digest": exp_authz_digest,
        },
    )

    # 5. Atomic claim. On replay (O_EXCL fails) the caller is NOT the
    #    claim owner and must reject immediately without spawning any
    #    operation-plan step and without creating, replacing, deleting,
    #    truncating, or otherwise mutating either receipt. The claim
    #    owner -- and only the claim owner -- has the right to create
    #    the terminal result file. ``claim present + result absent`` is
    #    itself the durable ``indeterminate/consumed`` state and needs
    #    no materialized result file; ``claim present + result present``
    #    is terminal/consumed. A hard crash can therefore leave
    #    claim-only forever.
    try:
        claim_digest = _atomic_claim_nonce(
            receipt_fd, claim_filename, claim_payload
        )
    except _ClaimExists:
        if _result_file_exists(receipt_fd, result_filename):
            raise FlutterExecutionExecutorError(
                f"execution nonce {nonce!r} already consumed "
                f"(claim and result both present)"
            )
        # Claim present, result absent: indeterminate/consumed state.
        # The replayer MUST NOT write a terminal result (that right
        # belongs to the claim owner only, which may still be running
        # concurrently). Raise without touching any receipt.
        raise FlutterExecutionExecutorError(
            f"execution nonce {nonce!r} indeterminate/consumed "
            f"(claim present without terminal result; not retryable)"
        )

    # 6. Execute steps. Any failure classifies a terminal status and
    #    writes the terminal result.
    overall_status = "success"
    step_results_report: list[dict[str, Any]] = []
    step_results_persist: list[dict[str, Any]] = []
    cancellation = False
    internal_error = False
    plan_steps = authorization["verified_binding"]["plan"]["steps"]
    step_authzs = authorization["step_authorizations"]
    env = _build_spawn_environment()
    i = 0

    try:
        for i, step in enumerate(plan_steps):
            sa = step_authzs[i]
            step_recorded = False

            # 6a. Re-verify before every spawn (re-runs the fixed
            #     transitive Flutter version preflight).
            try:
                authz_module.verify_authorization(
                    authorization,
                    expected_manifest_path=exp_manifest_path,
                    expected_manifest_sha256=exp_manifest_sha,
                    expected_binding_digest=exp_binding_digest,
                    expected_authorization_digest=exp_authz_digest,
                )
            except authz_module.FlutterExecutionAuthorizationError:
                overall_status = "verification_failure"
                step_results_report.append(
                    {
                        "step_index": i,
                        "step_id": sa["step_id"],
                        "status": "skipped",
                    }
                )
                step_results_persist.append(
                    {
                        "step_index": i,
                        "step_id": sa["step_id"],
                        "status": "skipped",
                    }
                )
                _mark_skipped(
                    i + 1, plan_steps, step_results_report, step_results_persist
                )
                break

            # 6b. Validate plan-step vs step-authorization equality.
            try:
                _validate_step_against_step_authz(step, sa, i)
            except _IntegrityError:
                overall_status = "integrity_failure"
                step_results_report.append(
                    {
                        "step_index": i,
                        "step_id": sa["step_id"],
                        "status": "skipped",
                    }
                )
                step_results_persist.append(
                    {
                        "step_index": i,
                        "step_id": sa["step_id"],
                        "status": "skipped",
                    }
                )
                _mark_skipped(
                    i + 1, plan_steps, step_results_report, step_results_persist
                )
                break

            # 6c. Copy bound argv to an immutable local tuple.
            try:
                argv_tuple = _build_argv_tuple(step)
            except _IntegrityError:
                overall_status = "integrity_failure"
                step_results_report.append(
                    {
                        "step_index": i,
                        "step_id": sa["step_id"],
                        "status": "skipped",
                    }
                )
                step_results_persist.append(
                    {
                        "step_index": i,
                        "step_id": sa["step_id"],
                        "status": "skipped",
                    }
                )
                _mark_skipped(
                    i + 1, plan_steps, step_results_report, step_results_persist
                )
                break

            # 6d. Pre-spawn argv[0]/executable/primitive/cwd recheck.
            # The actual immutable argv tuple's argv[0] is passed in so
            # the lexical equality check is real, not a constant.
            try:
                _pre_spawn_recheck(
                    argv0=argv_tuple[0],
                    primitive_path=sa["primitive_path"],
                    primitive_sha256=sa["primitive_sha256"],
                    executable_path=sa["executable_path"],
                    executable_sha256=sa["executable_sha256"],
                    cwd=sa["cwd"],
                )
            except _IntegrityError:
                overall_status = "integrity_failure"
                step_results_report.append(
                    {
                        "step_index": i,
                        "step_id": sa["step_id"],
                        "status": "skipped",
                    }
                )
                step_results_persist.append(
                    {
                        "step_index": i,
                        "step_id": sa["step_id"],
                        "status": "skipped",
                    }
                )
                _mark_skipped(
                    i + 1, plan_steps, step_results_report, step_results_persist
                )
                break

            # 6e. Spawn with shell=False, exact cwd, exact timeout,
            #     stdin=DEVNULL, close_fds=True, new session.
            timeout = _effective_timeout(sa["timeout_seconds"])
            try:
                spawn_result = _spawn_step(
                    argv_tuple=argv_tuple,
                    cwd=sa["cwd"],
                    timeout_seconds=timeout,
                    env=env,
                )
            except OSError:
                spawn_result = {
                    "status": "launch_error",
                    "exit_code": None,
                    "signal_number": None,
                    "stdout_byte_count": 0,
                    "stdout_sha256": _sha256_bytes(b""),
                    "stdout_tail_b64": "",
                    "stdout_truncated": False,
                    "stderr_byte_count": 0,
                    "stderr_sha256": _sha256_bytes(b""),
                    "stderr_tail_b64": "",
                    "stderr_truncated": False,
                }

            sr_report = {
                "step_index": i,
                "step_id": sa["step_id"],
                "primitive": sa["primitive"],
                "argv": list(argv_tuple),
                "cwd": sa["cwd"],
                "timeout_seconds": sa["timeout_seconds"],
                "shell": False,
                "start_new_session": True,
                "stdin_devnull": True,
                "close_fds": True,
                "argv_digest": sa["argv_digest"],
                "step_authorization_digest": sa["step_authorization_digest"],
                "executable_path": sa["executable_path"],
                "executable_sha256": sa["executable_sha256"],
                "primitive_path": sa["primitive_path"],
                "primitive_sha256": sa["primitive_sha256"],
                "status": spawn_result["status"],
                "exit_code": spawn_result["exit_code"],
                "signal_number": spawn_result["signal_number"],
                "stdout_byte_count": spawn_result["stdout_byte_count"],
                "stdout_sha256": spawn_result["stdout_sha256"],
                "stdout_tail_b64": spawn_result["stdout_tail_b64"],
                "stdout_truncated": spawn_result["stdout_truncated"],
                "stderr_byte_count": spawn_result["stderr_byte_count"],
                "stderr_sha256": spawn_result["stderr_sha256"],
                "stderr_tail_b64": spawn_result["stderr_tail_b64"],
                "stderr_truncated": spawn_result["stderr_truncated"],
            }
            sr_persist = {
                "step_index": i,
                "step_id": sa["step_id"],
                "status": spawn_result["status"],
                "exit_code": spawn_result["exit_code"],
                "signal_number": spawn_result["signal_number"],
                "stdout_byte_count": spawn_result["stdout_byte_count"],
                "stdout_sha256": spawn_result["stdout_sha256"],
                "stderr_byte_count": spawn_result["stderr_byte_count"],
                "stderr_sha256": spawn_result["stderr_sha256"],
                "stdout_truncated": spawn_result["stdout_truncated"],
                "stderr_truncated": spawn_result["stderr_truncated"],
            }
            step_results_report.append(sr_report)
            step_results_persist.append(sr_persist)

            if spawn_result["status"] == "success":
                continue
            if spawn_result["status"] == "timed_out":
                overall_status = "timeout"
            elif spawn_result["status"] == "launch_error":
                overall_status = "launch_error"
            elif spawn_result["status"] == "output_drain_failure":
                overall_status = "output_drain_failure"
            else:
                overall_status = "step_failure"
            _mark_skipped(
                i + 1, plan_steps, step_results_report, step_results_persist
            )
            break
    except KeyboardInterrupt:
        overall_status = "cancellation"
        cancellation = True
    except _IntegrityError:
        # An _IntegrityError that escapes the per-check handlers
        # (defensive): treat as integrity failure.
        overall_status = "integrity_failure"
        if i < len(plan_steps):
            step_results_report.append(
                {
                    "step_index": i,
                    "step_id": plan_steps[i]["step_id"],
                    "status": "skipped",
                }
            )
            step_results_persist.append(
                {
                    "step_index": i,
                    "step_id": plan_steps[i]["step_id"],
                    "status": "skipped",
                }
            )
            _mark_skipped(
                i + 1, plan_steps, step_results_report, step_results_persist
            )
    except Exception:
        # Unexpected internal error after claim: persist a
        # sanitized internal_error terminal result owned by the
        # claim owner, never leak the exception text, and stop
        # later steps.
        overall_status = "internal_error"
        if i < len(plan_steps):
            # Only append a skipped marker for step i if no
            # per-step result was already recorded for it (the
            # exception may have fired mid-step before the
            # spawn-result append, or after).
            already = bool(step_results_persist) and (
                step_results_persist[-1].get("step_index") == i
            )
            if not already:
                step_results_report.append(
                    {
                        "step_index": i,
                        "step_id": plan_steps[i]["step_id"],
                        "status": "skipped",
                    }
                )
                step_results_persist.append(
                    {
                        "step_index": i,
                        "step_id": plan_steps[i]["step_id"],
                        "status": "skipped",
                    }
                )
            _mark_skipped(
                i + 1, plan_steps, step_results_report, step_results_persist
            )
        internal_error = True

    # 7. Persist terminal result.
    result_payload = _build_result_payload(
        overall_status,
        nonce,
        claim_digest,
        exp_authz_digest,
        step_results_persist,
    )
    try:
        result_digest = _atomic_write_result(
            receipt_fd, result_filename, result_payload
        )
    except FlutterExecutionExecutorError:
        # A concurrent writer (crash race) wrote the result first.
        # Surface a non-success report; the persisted result is the
        # other writer's.
        result_digest = ""

    # 8. Build the returned versioned strict-schema report.
    report = {
        "kind": KIND_REPORT,
        "schema_version": SCHEMA_VERSION,
        "ok": overall_status == "success",
        "overall_status": overall_status,
        "execution_nonce": nonce,
        "expected_authorization_digest": exp_authz_digest,
        "authorization_digest": authorization["authorization_digest"],
        "claim_digest": claim_digest,
        "result_digest": result_digest,
        "step_results": step_results_report,
    }

    if cancellation:
        raise KeyboardInterrupt

    return report


def execute_authorization(
    authorization: dict[str, Any],
    *,
    expected_manifest_path: Any,
    expected_manifest_sha256: Any,
    expected_binding_digest: Any,
    expected_authorization_digest: Any,
) -> dict[str, Any]:
    """Execute a verified ``icp.flutter-execution-authorization-
    candidate`` envelope's exact ordered operation-plan steps.

    Requires all four trusted expected values:
    ``expected_manifest_path``, ``expected_manifest_sha256``,
    ``expected_binding_digest``, ``expected_authorization_digest``.
    None may default, be inferred from the untrusted document, or be
    optional.

    Pre-claim, calls
    :func:`flutter_execution_authorization_v1.verify_authorization`
    with all four expected values (re-running the fixed transitive
    Flutter version preflight subprocess). Derives the run root from
    the freshly verified candidate's embedded selection verification
    (cross-checked against ``Path(selection_manifest_path).parent``).
    Atomically claims the recorded execution nonce against the fixed
    receipt directory under the verified run root; rejects replays
    without spawning any operation step. Executes the embedded binding
    plan serially with the exact ordered argv, re-verifying and re-
    hashing executable/primitive/cwd bytes immediately before every
    spawn. Spawns with ``shell=False``, exact cwd, exact timeout,
    ``stdin=DEVNULL``, ``close_fds=True``, and a new process session/
    group; drains stdout/stderr fully with bounded 16-KiB tails;
    never persists raw output. Persists a sanitized terminal result
    that consumes the nonce forever for every outcome (success,
    non-zero exit, timeout, launch failure, verification drift,
    integrity drift, internal error, cancellation, or claim-only
    crash state).

    Returns a versioned strict-schema report. Raises
    :class:`FlutterExecutionExecutorError` on any pre-claim failure
    (verification, expected-value mismatch, run-root derivation,
    receipt-directory defense, or replay detection). Post-claim
    failures persist a terminal result and return a non-success
    report rather than raising.

    Honest TOCTOU boundary: path verification plus
    :func:`subprocess.Popen` does NOT eliminate the verify-to-spawn
    race for executable/script path replacement. The design narrows
    the window by immediate re-verification/re-hashing and exact
    spawn, but normal path-based execution retains a small check-to-
    exec TOCTOU residual. The fd-relative receipt claim closes the
    nonce filename symlink/replay race; it does not close
    executable/script path replacement races.

    Environment trust boundary: the executor-owned spawn environment
    is built from the trusted supervisor process environment and
    strips Python/dynamic-loader/shell startup injection variables,
    but this environment is **executor policy, not bound by P2e2a**.
    The supervisor process environment remains trusted input.
    """
    try:
        return _execute_impl(
            authorization,
            expected_manifest_path=expected_manifest_path,
            expected_manifest_sha256=expected_manifest_sha256,
            expected_binding_digest=expected_binding_digest,
            expected_authorization_digest=expected_authorization_digest,
        )
    except FlutterExecutionExecutorError:
        raise
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001
        raise FlutterExecutionExecutorError(
            f"execute_authorization raised {type(exc).__name__}"
        ) from exc
