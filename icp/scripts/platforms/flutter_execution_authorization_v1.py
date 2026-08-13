#!/usr/bin/env python3
"""ICP P2e2a non-executable Flutter execution authorization candidate.

This module produces a deterministic, **non-executable**, unsigned
candidate ``icp.flutter-execution-authorization-candidate`` envelope
from an existing verified ``icp.flutter-execution-binding.v1`` binding.
The candidate is **not** self-authorizing authority: the trusted
supervisor must retain these expected values out of band:

* the canonical selection-manifest path;
* the selection-manifest SHA-256;
* the verified binding digest;
* the prepared authorization digest.

An attacker who can rewrite workspace files cannot authorize a different
valid binding merely by recomputing in-document digests:
:func:`verify_authorization` requires all four expected values; none
may default, be inferred from the untrusted document, or be optional.

Process / I/O boundary (truthful):

* **No operation-plan command is executed.** This slice never spawns
  the per-step argv plans recorded in the binding.
* **No direct subprocess, shell, network, or filesystem-write surface
  exists in this module.** It never imports ``subprocess``/``socket``/
  ``urllib``/``http.client``, never uses ``shell=True``, never writes
  a file, never creates a symlink, never spawns a process directly,
  and exposes no CLI.
* **The shared binding verifier is intentionally re-entered on every
  prepare and verify call**, and that verifier re-runs the fixed
  read-only Flutter project preflight
  ``subprocess.run([resolved_flutter, "--version", "--machine"],
  shell=False, ...)``. Therefore ``prepare_authorization`` and
  ``verify_authorization`` CAN cause that one fixed, read-only child
  process to run, and CAN fail if that fixed preflight fails (no
  Flutter on PATH, wrong version, etc.). This is the only process
  surface in the transitive call chain, and it is owned by
  ``flutter_project_preflight_v1.preflight``, not by this module.
* Importing this module performs **no** filesystem I/O: the installed
  binding-module path is derived purely lexically
  (``Path(os.path.abspath(__file__)).parent``), and every
  resolve/lstat/read happens lazily inside ``_load_binding_module`` /
  the per-step binders.
* No receipt is written; the project/state/run roots are not mutated
  by this module; no platform adapter is activated; the execution
  nonce is only recorded (never consumed).

P2e2b must call :func:`verify_authorization` immediately before any
spawn, must atomically claim the recorded nonce (single-writer
compare-and-swap keyed on the supervisor-held expected authorization
digest), and must re-check executable and primitive-script bytes /
paths immediately before each exact argv spawn. A normal path-based
spawn still retains a small check-to-exec race after these checks;
P2e2b must report that residual unless a separately implemented and
tested OS-specific fd-bound execution mechanism actually closes it.
This slice alone does **not** eliminate the verify-to-spawn TOCTOU
window.

Public Python API (no CLI):

* ``prepare_authorization(binding, *, expected_manifest_path,
     expected_manifest_sha256, expected_binding_digest,
     execution_nonce) -> dict``
* ``verify_authorization(authorization, *, expected_manifest_path,
     expected_manifest_sha256, expected_binding_digest,
     expected_authorization_digest) -> dict``

Only these two functions plus the module-local typed exception
:class:`FlutterExecutionAuthorizationError` may be public.

Locked boundaries:

* Stdlib only. No ``subprocess`` import, no shell, no network, no
  filesystem write, no symlink create, no CLI, no import-time I/O.
  The transitive Flutter preflight subprocess is owned by the shared
  binding verifier's preflight module, not by this module.
* Production code derives the binding module path only from this
  module's installed file location, purely lexically. The real
  strict-resolve / regular-file / non-symlink integrity checks for
  that path run lazily inside ``_load_binding_module``. No public
  override is exposed.
* ``prepare_authorization`` and ``verify_authorization`` both call the
  shared :func:`flutter_execution_binding_v1.verify_binding` rather
  than duplicating or weakening it.
* For every binding plan step the per-step authorization binds: step id
  and primitive identity; primitive/script path and current SHA-256;
  the full argv digest (the full argv remains in the embedded binding);
  canonical cwd; timeout; ``argv[0]`` executable canonical path and
  current SHA-256; and a deterministic step-authorization digest over
  all these fields.
* ``argv[0]`` is bound to the current ``sys.executable`` (lexical
  equality) and to its canonical realpath target (which must exist, be
  a regular file, and not itself be a symlink).
* ``argv[1]`` is bound to the already-verified primitive script named
  by the step (canonical, existing, regular, non-symlink, and hash-equal
  to the step's ``primitive_sha256``).
* Canonical JSON for the authorization is UTF-8, sorted keys, compact
  separators ``(",", ":")``, ``allow_nan=False``, deterministic across
  repeated calls; digests hash those bytes with SHA-256.
* No timestamps, environment snapshots, hostnames, random values, or
  nondeterministic ordering.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Public schema constants.
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1
KIND_AUTHZ = "icp.flutter-execution-authorization-candidate"
KIND_AUTHZ_VERIFY = "icp.flutter-execution-authorization-verify.v1"
PLATFORM_ID = "flutter"
PROFILE_ID = "flutter-standard"
ACTIVATION_STATE = "inactive"
EXECUTABLE = False

# Local error code (does not extend icp_common.ALL_ERROR_CODES).
CODE = "flutter_execution_authorization_failed"

# ---------------------------------------------------------------------------
# Fixed production paths derived from this module's installed location.
# Accepts NO override; this is the runtime surface.
#
# This is a PURELY LEXICAL derivation: ``os.path.abspath`` only collapses
# ``.``/``..`` syntactically and never touches the filesystem. The
# real filesystem-resolution / regular-file / non-symlink integrity
# checks for ``_BINDING_PATH`` run lazily inside ``_load_binding_module``
# (never at import time), so importing this module performs no
# filesystem I/O at all.
# ---------------------------------------------------------------------------

_PLATFORMS_DIR = Path(os.path.abspath(__file__)).parent
_BINDING_PATH = _PLATFORMS_DIR / "flutter_execution_binding_v1.py"

# Exact whole-string execution-nonce grammar: 32 lowercase hex chars.
# Enforced with :meth:`re.Pattern.fullmatch` so trailing newline, CR, LF,
# space, uppercase, or any extra character is rejected.
_NONCE_RE = re.compile(r"[0-9a-f]{32}")

# Exact top-level authorization key set (frozen contract).
_AUTHZ_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "platform_id",
        "profile_id",
        "activation_state",
        "executable",
        "operation_id",
        "port_id",
        "capability_state",
        "selection_manifest_path",
        "selection_manifest_sha256",
        "binding_digest",
        "execution_nonce",
        "verified_binding",
        "step_authorizations",
        "authorization_digest",
    }
)

# Exact verify-report key set.
_VERIFY_KEYS = frozenset(
    {
        "ok",
        "kind",
        "schema_version",
        "platform_id",
        "operation_id",
        "port_id",
        "binding_digest",
        "selection_manifest_sha256",
        "authorization_digest",
        "execution_nonce",
    }
)

# Exact per-step authorization key set.
_STEP_AUTHZ_KEYS = frozenset(
    {
        "step_id",
        "primitive",
        "primitive_path",
        "primitive_sha256",
        "argv_digest",
        "cwd",
        "timeout_seconds",
        "executable_path",
        "executable_sha256",
        "step_authorization_digest",
    }
)

# Per-step authorization field order. Used to build the canonical
# step payload that excludes only the self-referential digest.
_STEP_PAYLOAD_FIELDS = (
    "step_id",
    "primitive",
    "primitive_path",
    "primitive_sha256",
    "argv_digest",
    "cwd",
    "timeout_seconds",
    "executable_path",
    "executable_sha256",
)

# Top-level authorization field order. Used to build the canonical
# top-level payload that excludes only the self-referential digest.
_AUTHZ_PAYLOAD_FIELDS = (
    "kind",
    "schema_version",
    "platform_id",
    "profile_id",
    "activation_state",
    "executable",
    "operation_id",
    "port_id",
    "capability_state",
    "selection_manifest_path",
    "selection_manifest_sha256",
    "binding_digest",
    "execution_nonce",
    "verified_binding",
    "step_authorizations",
)


class FlutterExecutionAuthorizationError(Exception):
    """A local Flutter execution authorization failure.

    Raised for any binding/verification/shape/digest/path/nonce mismatch.
    Generic failures are converted at the public API boundary to
    instances of this class whose message exposes the original
    exception's type name only; arbitrary exception text is never leaked.
    """


# ---------------------------------------------------------------------------
# Lazy module loader for the binding module (no sys.path mutation).
# ---------------------------------------------------------------------------

_BINDING_MODULE: Any = None


def _load_module_by_path(name: str, path: Path):
    """Load ``path`` as a module under ``name`` without touching sys.path."""
    try:
        if path.is_symlink():
            raise FlutterExecutionAuthorizationError(
                f"refusing symlink module: {path}"
            )
        st = path.lstat()
    except OSError as exc:
        raise FlutterExecutionAuthorizationError(
            f"cannot lstat module {path}: {type(exc).__name__}"
        ) from exc
    if not stat.S_ISREG(st.st_mode):
        raise FlutterExecutionAuthorizationError(
            f"module not a regular file: {path}"
        )
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise FlutterExecutionAuthorizationError(
            f"cannot load module spec: {path}"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_binding_module():
    """Load the shared Flutter execution binding module.

    Performs the lazy filesystem integrity check that the lexical
    ``_BINDING_PATH`` strict-resolves to itself (so a symlinked
    ancestor redirecting the path is rejected), then delegates to
    :func:`_load_module_by_path` for the non-symlink-leaf, regular-file
    and module-spec checks. All filesystem I/O happens here at first
    call, never at import time."""
    global _BINDING_MODULE
    if _BINDING_MODULE is None:
        # Lazy strict-resolve identity check (replaces the previous
        # import-time ``Path(__file__).resolve()``). This catches a
        # symlinked ancestor redirecting the binding path; the leaf
        # non-symlink/regular-file check is delegated below.
        try:
            resolved = _BINDING_PATH.resolve(strict=True)
        except FileNotFoundError as exc:
            raise FlutterExecutionAuthorizationError(
                f"binding module not found: {_BINDING_PATH}"
            ) from exc
        except RuntimeError as exc:
            raise FlutterExecutionAuthorizationError(
                f"binding module resolve loop: {type(exc).__name__}"
            ) from exc
        except OSError as exc:
            raise FlutterExecutionAuthorizationError(
                f"binding module resolve failed: {type(exc).__name__}"
            ) from exc
        if resolved != _BINDING_PATH:
            raise FlutterExecutionAuthorizationError(
                f"binding module path differs from strict resolve "
                f"(symlinked ancestor): {_BINDING_PATH} -> {resolved}"
            )
        _BINDING_MODULE = _load_module_by_path(
            "flutter_execution_binding_v1_p2e2a", _BINDING_PATH
        )
    return _BINDING_MODULE


# ---------------------------------------------------------------------------
# Canonical JSON / digest helpers.
# ---------------------------------------------------------------------------


def _canonical_compact_bytes(payload: Any) -> bytes:
    """Canonical JSON bytes for the authorization candidate.

    UTF-8, sorted keys, compact separators, ``allow_nan=False``. Raises
    :class:`ValueError` (converted at the public boundary) if the
    payload contains NaN/Infinity."""
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise FlutterExecutionAuthorizationError(
            f"cannot read {path}: {type(exc).__name__}"
        ) from exc


def _is_sha256_hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value.islower()
        and all(c in "0123456789abcdef" for c in value)
    )


# ---------------------------------------------------------------------------
# JSON-suitability walker. Rejects any non-JSON type and NaN/Infinity.
# ---------------------------------------------------------------------------


def _is_canonical_json_suitable(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        if value != value or value == float("inf") or value == float("-inf"):
            return False
        return True
    if isinstance(value, str):
        return True
    if value is None:
        return True
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                return False
            if not _is_canonical_json_suitable(v):
                return False
        return True
    if isinstance(value, list):
        return all(_is_canonical_json_suitable(v) for v in value)
    return False


# ---------------------------------------------------------------------------
# Typed scalar / shape validators.
# ---------------------------------------------------------------------------


def _require_str(value: Any, role: str) -> str:
    if not isinstance(value, str):
        raise FlutterExecutionAuthorizationError(
            f"{role}: must be a string, got {type(value).__name__}"
        )
    return value


def _require_bool(value: Any, role: str) -> bool:
    if value is True or value is False:
        return value
    raise FlutterExecutionAuthorizationError(
        f"{role}: must be a bool, got {type(value).__name__}"
    )


def _require_int(value: Any, role: str) -> int:
    # Explicitly reject bool (a subclass of int).
    if isinstance(value, bool):
        raise FlutterExecutionAuthorizationError(
            f"{role}: must be an int, got bool"
        )
    if not isinstance(value, int):
        raise FlutterExecutionAuthorizationError(
            f"{role}: must be an int, got {type(value).__name__}"
        )
    return value


def _require_dict(value: Any, role: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FlutterExecutionAuthorizationError(
            f"{role}: must be an object, got {type(value).__name__}"
        )
    return value


def _require_list(value: Any, role: str) -> list[Any]:
    if not isinstance(value, list):
        raise FlutterExecutionAuthorizationError(
            f"{role}: must be a list, got {type(value).__name__}"
        )
    return value


def _require_sha256_hex(value: Any, role: str) -> str:
    if not _is_sha256_hex(value):
        raise FlutterExecutionAuthorizationError(
            f"{role}: malformed sha256: {value!r}"
        )
    return value


# ---------------------------------------------------------------------------
# Trusted-supplied expected-value validators.
# ---------------------------------------------------------------------------


def _validate_expected_manifest_path(value: Any) -> str:
    """Validate the supervisor-supplied canonical manifest path.

    The trusted anchor must be a string. The authorization does not
    require the path to exist at prepare/verify time (the existence
    check belongs to the binding's selection verifier); it only
    requires that the string exactly equal the embedded verified
    binding's ``selection_manifest_path``."""
    return _require_str(value, "expected_manifest_path")


def _validate_expected_sha(value: Any, role: str) -> str:
    return _require_sha256_hex(value, role)


def _validate_execution_nonce(value: Any) -> str:
    """Validate the caller-supplied execution nonce.

    Grammar: exactly 32 lowercase hex characters. Enforced with
    :meth:`re.Pattern.fullmatch` so trailing newline, CR, LF, space,
    uppercase, wrong length, non-string, or any extra character is
    rejected. The nonce is caller-supplied only; this module never
    generates randomness."""
    if not isinstance(value, str):
        raise FlutterExecutionAuthorizationError(
            f"execution_nonce: must be a string, got {type(value).__name__}"
        )
    if not _NONCE_RE.fullmatch(value):
        raise FlutterExecutionAuthorizationError(
            f"execution_nonce: must be exactly 32 lowercase hex chars, "
            f"got {value!r}"
        )
    return value


# ---------------------------------------------------------------------------
# Executable / primitive script canonicalization (re-hashed on every call).
# ---------------------------------------------------------------------------


def _current_executable() -> str:
    """Return the current interpreter's lexical ``sys.executable``.

    Test seam: tests that need to drive the fail-closed branch of the
    executable canonicalization without modifying the real interpreter
    patch this function to return a controlled path."""
    return sys.executable


def _check_canonical_regular_nonsymlink(path: Path, role: str) -> None:
    """Require ``path`` (already a realpath canonical target) to exist,
    be a regular file, and not itself be a symlink."""
    try:
        if path.is_symlink():
            raise FlutterExecutionAuthorizationError(
                f"{role}: refusing symlink target: {path}"
            )
        st = path.lstat()
    except FileNotFoundError as exc:
        raise FlutterExecutionAuthorizationError(
            f"{role}: not found: {path}"
        ) from exc
    except OSError as exc:
        raise FlutterExecutionAuthorizationError(
            f"{role}: cannot lstat: {type(exc).__name__}"
        ) from exc
    if not stat.S_ISREG(st.st_mode):
        raise FlutterExecutionAuthorizationError(
            f"{role}: not a regular file: {path}"
        )


def _bind_current_executable(argv0: Any) -> tuple[str, str]:
    """Bind ``argv[0]`` to the current interpreter.

    ``argv[0]`` must equal ``sys.executable`` lexically. The canonical
    realpath target of ``argv[0]`` must equal the canonical realpath
    target of the current interpreter, must exist, must be a regular
    file, and must not itself be a symlink (the resolved binary).

    Returns ``(canonical_path_str, sha256_hex_of_bytes)``.

    On macOS Homebrew the lexical ``sys.executable`` is itself a symlink
    into the framework; the canonical realpath target is the real
    framework binary, which is regular and not a symlink. The lexical
    equality check rejects any other symlink substituted for the
    interpreter; the realpath equality check is defence-in-depth.
    """
    if not isinstance(argv0, str):
        raise FlutterExecutionAuthorizationError(
            f"argv[0]: must be a string, got {type(argv0).__name__}"
        )
    current = _current_executable()
    if argv0 != current:
        raise FlutterExecutionAuthorizationError(
            "argv[0]: must equal current sys.executable"
        )
    current_real = os.path.realpath(current)
    argv0_real = os.path.realpath(argv0)
    if argv0_real != current_real:
        raise FlutterExecutionAuthorizationError(
            "argv[0]: canonical realpath must equal current interpreter "
            "canonical realpath"
        )
    canonical = Path(current_real)
    _check_canonical_regular_nonsymlink(canonical, "argv[0] executable")
    sha = _sha256_file(canonical)
    return current_real, sha


def _bind_primitive_script(
    argv1: Any, primitive: str, expected_sha: str
) -> tuple[str, str]:
    """Bind ``argv[1]`` to the already-verified primitive script.

    The script path must:
    * be a string;
    * be absolute and lexically normalized (no ``..``);
    * not be a symlink at the lexical leaf;
    * be an existing regular file;
    * hash-equal (SHA-256 of current bytes) to ``expected_sha``.

    Returns ``(canonical_path_str, sha256_hex)``. The hash is recomputed
    on every call; any drift fails closed.
    """
    role = f"argv[1] primitive {primitive!r}"
    if not isinstance(argv1, str):
        raise FlutterExecutionAuthorizationError(
            f"{role}: must be a string, got {type(argv1).__name__}"
        )
    raw = Path(argv1)
    if not raw.is_absolute():
        raise FlutterExecutionAuthorizationError(f"{role}: not absolute: {argv1!r}")
    if any(part == ".." for part in raw.parts):
        raise FlutterExecutionAuthorizationError(
            f"{role}: contains '..': {argv1!r}"
        )
    if os.path.normpath(argv1) != argv1:
        raise FlutterExecutionAuthorizationError(
            f"{role}: not lexically normalized: {argv1!r}"
        )
    try:
        if raw.is_symlink():
            raise FlutterExecutionAuthorizationError(
                f"{role}: refusing symlink: {raw}"
            )
        st = raw.lstat()
    except FileNotFoundError as exc:
        raise FlutterExecutionAuthorizationError(
            f"{role}: not found: {raw}"
        ) from exc
    except OSError as exc:
        raise FlutterExecutionAuthorizationError(
            f"{role}: cannot lstat: {type(exc).__name__}"
        ) from exc
    if not stat.S_ISREG(st.st_mode):
        raise FlutterExecutionAuthorizationError(
            f"{role}: not a regular file: {raw}"
        )
    actual_sha = _sha256_file(raw)
    if actual_sha != expected_sha:
        raise FlutterExecutionAuthorizationError(
            f"{role}: sha256 mismatch (digest drift)"
        )
    return argv1, actual_sha


def _bind_step_cwd(cwd: Any) -> str:
    """Validate the canonical cwd string from the embedded binding step."""
    if not isinstance(cwd, str):
        raise FlutterExecutionAuthorizationError(
            f"cwd: must be a string, got {type(cwd).__name__}"
        )
    if not os.path.isabs(cwd):
        raise FlutterExecutionAuthorizationError(f"cwd: not absolute: {cwd!r}")
    if any(part == ".." for part in Path(cwd).parts):
        raise FlutterExecutionAuthorizationError(
            f"cwd: contains '..': {cwd!r}"
        )
    if os.path.normpath(cwd) != cwd:
        raise FlutterExecutionAuthorizationError(
            f"cwd: not lexically normalized: {cwd!r}"
        )
    return cwd


# ---------------------------------------------------------------------------
# Per-step authorization computation (single source of truth).
# ---------------------------------------------------------------------------


def _compute_step_authorization(step: dict[str, Any]) -> dict[str, Any]:
    """Compute the canonical per-step authorization for one embedded
    binding plan step.

    Validates ``argv[0]`` is the current interpreter and ``argv[1]`` is
    the already-verified primitive script, hashes their current bytes,
    computes the argv digest over the full argv list, and emits the
    deterministic step authorization (including the step-authorization
    digest). Used by both :func:`_prepare_authorization_impl` (the value
    stored in the candidate) and :func:`_verify_authorization_impl`
    (the value compared against the candidate).
    """
    # Strict step key set (the embedded binding already enforces this,
    # but the authorization module fails closed independently).
    if set(step.keys()) != {
        "step_id",
        "primitive",
        "primitive_sha256",
        "argv",
        "cwd",
        "timeout_seconds",
    }:
        extra = set(step.keys()) - {
            "step_id",
            "primitive",
            "primitive_sha256",
            "argv",
            "cwd",
            "timeout_seconds",
        }
        missing = {
            "step_id",
            "primitive",
            "primitive_sha256",
            "argv",
            "cwd",
            "timeout_seconds",
        } - set(step.keys())
        raise FlutterExecutionAuthorizationError(
            f"step keys mismatch: extra={sorted(extra)} missing={sorted(missing)}"
        )
    step_id = _require_str(step["step_id"], "step.step_id")
    primitive = _require_str(step["primitive"], "step.primitive")
    primitive_sha = _require_sha256_hex(
        step["primitive_sha256"], "step.primitive_sha256"
    )
    argv = _require_list(step["argv"], "step.argv")
    if len(argv) < 2:
        raise FlutterExecutionAuthorizationError(
            f"step.argv: must have at least 2 elements, got {len(argv)}"
        )
    cwd = _bind_step_cwd(step["cwd"])
    timeout = _require_int(step["timeout_seconds"], "step.timeout_seconds")
    # argv[0] executable canonical + current SHA-256.
    executable_path, executable_sha = _bind_current_executable(argv[0])
    # argv[1] primitive script canonical + current SHA-256 (must equal
    # the step's primitive_sha256).
    primitive_path, primitive_path_sha = _bind_primitive_script(
        argv[1], primitive, primitive_sha
    )
    # The primitive_path hash and the step primitive_sha256 must agree.
    if primitive_path_sha != primitive_sha:
        raise FlutterExecutionAuthorizationError(
            f"argv[1] primitive {primitive!r}: path sha256 != step primitive_sha256"
        )
    # Full argv digest over canonical compact JSON of the argv list.
    # The full argv remains in the embedded binding; this digest binds
    # every positional/flag/value element beyond argv[0] and argv[1].
    if not _is_canonical_json_suitable(argv):
        raise FlutterExecutionAuthorizationError(
            "step.argv: not canonical-JSON suitable"
        )
    argv_digest = _sha256_bytes(_canonical_compact_bytes(argv))
    # Build the canonical step payload (all fields except the
    # self-referential step_authorization_digest).
    payload = {
        "step_id": step_id,
        "primitive": primitive,
        "primitive_path": primitive_path,
        "primitive_sha256": primitive_sha,
        "argv_digest": argv_digest,
        "cwd": cwd,
        "timeout_seconds": timeout,
        "executable_path": executable_path,
        "executable_sha256": executable_sha,
    }
    step_digest = _sha256_bytes(_canonical_compact_bytes(payload))
    payload["step_authorization_digest"] = step_digest
    return payload


def _compute_step_authorizations(binding: dict[str, Any]) -> list[dict[str, Any]]:
    """Compute the ordered list of per-step authorizations from the
    embedded binding's plan steps."""
    plan = _require_dict(binding["plan"], "verified_binding.plan")
    steps = _require_list(plan["steps"], "verified_binding.plan.steps")
    return [_compute_step_authorization(step) for step in steps]


# ---------------------------------------------------------------------------
# Top-level authorization digest computation.
# ---------------------------------------------------------------------------


def _compute_authorization_digest(authorization_without_digest: dict[str, Any]) -> str:
    """Compute the top-level authorization digest over a canonical
    payload that excludes only the self-referential ``authorization_digest``
    field."""
    if not _is_canonical_json_suitable(authorization_without_digest):
        raise FlutterExecutionAuthorizationError(
            "authorization: not canonical-JSON suitable (NaN/Infinity/"
            "non-JSON value present)"
        )
    return _sha256_bytes(_canonical_compact_bytes(authorization_without_digest))


# ---------------------------------------------------------------------------
# prepare_authorization implementation.
# ---------------------------------------------------------------------------


def _prepare_authorization_impl(
    binding: dict[str, Any],
    *,
    expected_manifest_path: Any,
    expected_manifest_sha256: Any,
    expected_binding_digest: Any,
    execution_nonce: Any,
) -> dict[str, Any]:
    # 1. Validate every trusted-supplied expected value before any
    #    binding inspection. None may default, be inferred, or be
    #    optional.
    exp_manifest_path = _validate_expected_manifest_path(expected_manifest_path)
    exp_manifest_sha = _validate_expected_sha(
        expected_manifest_sha256, "expected_manifest_sha256"
    )
    exp_binding_digest = _validate_expected_sha(
        expected_binding_digest, "expected_binding_digest"
    )
    nonce = _validate_execution_nonce(execution_nonce)

    if not isinstance(binding, dict):
        raise FlutterExecutionAuthorizationError(
            f"binding: must be a dict, got {type(binding).__name__}"
        )

    # 2. Re-attest the binding through the shared verify_binding. This
    #    re-runs the complete preparation chain (selection verification,
    #    capsule, descriptor, preflight, plan build + verify) and
    #    requires exact equality with the candidate binding.
    binding_module = _load_binding_module()
    verify_report = binding_module.verify_binding(binding)

    # 3. Cross-check the trusted expected values against the verified
    #    binding and its verify report. Each comparison is independent;
    #    any mismatch fails closed.
    binding_manifest_path = _require_str(
        binding.get("selection_manifest_path"),
        "binding.selection_manifest_path",
    )
    binding_manifest_sha = _require_sha256_hex(
        binding.get("selection_manifest_sha256"),
        "binding.selection_manifest_sha256",
    )
    if exp_manifest_path != binding_manifest_path:
        raise FlutterExecutionAuthorizationError(
            "expected_manifest_path != binding.selection_manifest_path"
        )
    if exp_manifest_sha != binding_manifest_sha:
        raise FlutterExecutionAuthorizationError(
            "expected_manifest_sha256 != binding.selection_manifest_sha256"
        )
    if exp_manifest_sha != verify_report["selection_manifest_sha256"]:
        raise FlutterExecutionAuthorizationError(
            "expected_manifest_sha256 != verify_report manifest sha"
        )
    if exp_binding_digest != verify_report["binding_digest"]:
        raise FlutterExecutionAuthorizationError(
            "expected_binding_digest != verify_report binding_digest"
        )

    # 4. The authorization embeds a deep, JSON-safe snapshot of the
    #    complete verified binding. Reject any non-JSON-safe binding.
    embedded_binding = copy.deepcopy(binding)
    if not _is_canonical_json_suitable(embedded_binding):
        raise FlutterExecutionAuthorizationError(
            "binding: not canonical-JSON suitable (NaN/Infinity/"
            "non-JSON value present)"
        )

    # 5. Compute the ordered per-step authorizations. This re-hashes
    #    the current interpreter and primitive script bytes for every
    #    step and binds argv[0]/argv[1]/cwd/timeout/argv digest.
    step_authorizations = _compute_step_authorizations(embedded_binding)

    # 6. Carry exact platform/profile/operation identity copied from
    #    the verified binding.
    authorization: dict[str, Any] = {
        "kind": KIND_AUTHZ,
        "schema_version": SCHEMA_VERSION,
        "platform_id": binding["platform_id"],
        "profile_id": binding["profile_id"],
        "activation_state": ACTIVATION_STATE,
        "executable": EXECUTABLE,
        "operation_id": binding["operation_id"],
        "port_id": binding["port_id"],
        "capability_state": binding["capability_state"],
        "selection_manifest_path": binding_manifest_path,
        "selection_manifest_sha256": binding_manifest_sha,
        "binding_digest": exp_binding_digest,
        "execution_nonce": nonce,
        "verified_binding": embedded_binding,
        "step_authorizations": step_authorizations,
    }
    # 7. Top-level authorization digest over the canonical payload that
    #    excludes only the self-referential authorization_digest.
    authorization["authorization_digest"] = _compute_authorization_digest(
        {k: v for k, v in authorization.items() if k != "authorization_digest"}
    )
    return authorization


def prepare_authorization(
    binding: dict[str, Any],
    *,
    expected_manifest_path: Any,
    expected_manifest_sha256: Any,
    expected_binding_digest: Any,
    execution_nonce: Any,
) -> dict[str, Any]:
    """Prepare a deterministic ``icp.flutter-execution-authorization-
    candidate`` envelope from an existing verified
    ``icp.flutter-execution-binding.v1`` binding.

    Requires all four trusted expected values:
    ``expected_manifest_path``, ``expected_manifest_sha256``,
    ``expected_binding_digest``, and the caller-supplied
    ``execution_nonce`` (exactly 32 lowercase hex chars).

    Re-attests the binding through the shared
    :func:`flutter_execution_binding_v1.verify_binding`, cross-checks
    the trusted expected values against the verified binding/report,
    embeds a deep JSON-safe snapshot of the verified binding, and binds
    every plan step's argv[0]/argv[1]/cwd/timeout/argv digest to the
    current interpreter and primitive script bytes.

    The slice is **non-executable**: ``activation_state`` is always
    ``inactive``, ``executable`` is always ``False``, no operation-plan
    command is executed, no receipt is written, no project/state/run
    root is mutated by this module, no platform adapter is activated,
    and the execution nonce is only recorded (never consumed).

    Note that re-attesting the binding through
    :func:`flutter_execution_binding_v1.verify_binding` re-runs the
    fixed read-only Flutter project preflight
    ``[resolved_flutter, "--version", "--machine"]`` (``shell=False``),
    which is the one transitive child process owned by the shared
    binding verifier's preflight module. This call can fail if that
    fixed preflight fails.

    Raises :class:`FlutterExecutionAuthorizationError` on any failure;
    generic exceptions are wrapped to type-only messages.
    """
    try:
        return _prepare_authorization_impl(
            binding,
            expected_manifest_path=expected_manifest_path,
            expected_manifest_sha256=expected_manifest_sha256,
            expected_binding_digest=expected_binding_digest,
            execution_nonce=execution_nonce,
        )
    except FlutterExecutionAuthorizationError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise FlutterExecutionAuthorizationError(
            f"prepare_authorization raised {type(exc).__name__}"
        ) from exc


# ---------------------------------------------------------------------------
# verify_authorization implementation.
# ---------------------------------------------------------------------------


def _validate_authorization_shape(authorization: dict[str, Any]) -> None:
    """Strict shape/literal/digest validation before any binding work."""
    keys = set(authorization.keys())
    if keys != _AUTHZ_KEYS:
        extra = sorted(keys - _AUTHZ_KEYS)
        missing = sorted(_AUTHZ_KEYS - keys)
        raise FlutterExecutionAuthorizationError(
            f"authorization keys mismatch: extra={extra} missing={missing}"
        )
    if authorization["kind"] != KIND_AUTHZ:
        raise FlutterExecutionAuthorizationError(
            f"authorization kind mismatch: {authorization['kind']!r}"
        )
    if _require_int(authorization["schema_version"], "schema_version") != SCHEMA_VERSION:
        raise FlutterExecutionAuthorizationError(
            f"authorization schema_version mismatch: "
            f"{authorization['schema_version']!r}"
        )
    if authorization["platform_id"] != PLATFORM_ID:
        raise FlutterExecutionAuthorizationError(
            f"authorization platform_id mismatch: "
            f"{authorization['platform_id']!r}"
        )
    if authorization["profile_id"] != PROFILE_ID:
        raise FlutterExecutionAuthorizationError(
            f"authorization profile_id mismatch: "
            f"{authorization['profile_id']!r}"
        )
    if authorization["activation_state"] != ACTIVATION_STATE:
        raise FlutterExecutionAuthorizationError(
            f"authorization activation_state mismatch: "
            f"{authorization['activation_state']!r}"
        )
    if _require_bool(authorization["executable"], "executable") is not False:
        raise FlutterExecutionAuthorizationError(
            "authorization executable must be false"
        )
    _require_str(authorization["operation_id"], "operation_id")
    _require_str(authorization["port_id"], "port_id")
    _require_str(authorization["capability_state"], "capability_state")
    _require_str(authorization["selection_manifest_path"], "selection_manifest_path")
    _require_sha256_hex(
        authorization["selection_manifest_sha256"],
        "selection_manifest_sha256",
    )
    _require_sha256_hex(authorization["binding_digest"], "binding_digest")
    _validate_execution_nonce(authorization["execution_nonce"])
    _require_dict(authorization["verified_binding"], "verified_binding")
    steps = _require_list(authorization["step_authorizations"], "step_authorizations")
    for i, sa in enumerate(steps):
        if not isinstance(sa, dict):
            raise FlutterExecutionAuthorizationError(
                f"step_authorizations[{i}]: must be an object, "
                f"got {type(sa).__name__}"
            )
        sa_keys = set(sa.keys())
        if sa_keys != _STEP_AUTHZ_KEYS:
            extra = sorted(sa_keys - _STEP_AUTHZ_KEYS)
            missing = sorted(_STEP_AUTHZ_KEYS - sa_keys)
            raise FlutterExecutionAuthorizationError(
                f"step_authorizations[{i}] keys mismatch: "
                f"extra={extra} missing={missing}"
            )
        _require_str(sa["step_id"], f"step_authorizations[{i}].step_id")
        _require_str(sa["primitive"], f"step_authorizations[{i}].primitive")
        _require_str(
            sa["primitive_path"], f"step_authorizations[{i}].primitive_path"
        )
        _require_sha256_hex(
            sa["primitive_sha256"],
            f"step_authorizations[{i}].primitive_sha256",
        )
        _require_sha256_hex(
            sa["argv_digest"], f"step_authorizations[{i}].argv_digest"
        )
        _require_str(sa["cwd"], f"step_authorizations[{i}].cwd")
        _require_int(
            sa["timeout_seconds"],
            f"step_authorizations[{i}].timeout_seconds",
        )
        _require_str(
            sa["executable_path"],
            f"step_authorizations[{i}].executable_path",
        )
        _require_sha256_hex(
            sa["executable_sha256"],
            f"step_authorizations[{i}].executable_sha256",
        )
        _require_sha256_hex(
            sa["step_authorization_digest"],
            f"step_authorizations[{i}].step_authorization_digest",
        )
    _require_sha256_hex(
        authorization["authorization_digest"], "authorization_digest"
    )


def _verify_authorization_impl(
    authorization: Any,
    *,
    expected_manifest_path: Any,
    expected_manifest_sha256: Any,
    expected_binding_digest: Any,
    expected_authorization_digest: Any,
) -> dict[str, Any]:
    if not isinstance(authorization, dict):
        raise FlutterExecutionAuthorizationError(
            f"authorization: must be a dict, got {type(authorization).__name__}"
        )

    # 1. Validate every trusted-supplied expected value. None may
    #    default, be inferred from the untrusted document, or be
    #    optional.
    exp_manifest_path = _validate_expected_manifest_path(expected_manifest_path)
    exp_manifest_sha = _validate_expected_sha(
        expected_manifest_sha256, "expected_manifest_sha256"
    )
    exp_binding_digest = _validate_expected_sha(
        expected_binding_digest, "expected_binding_digest"
    )
    exp_authz_digest = _validate_expected_sha(
        expected_authorization_digest, "expected_authorization_digest"
    )

    # 2. Strict shape/literal/digest validation.
    _validate_authorization_shape(authorization)

    # 3. Top-level expected-value comparisons. Each is independent.
    if exp_manifest_path != authorization["selection_manifest_path"]:
        raise FlutterExecutionAuthorizationError(
            "expected_manifest_path != authorization.selection_manifest_path"
        )
    if exp_manifest_sha != authorization["selection_manifest_sha256"]:
        raise FlutterExecutionAuthorizationError(
            "expected_manifest_sha256 != "
            "authorization.selection_manifest_sha256"
        )
    if exp_binding_digest != authorization["binding_digest"]:
        raise FlutterExecutionAuthorizationError(
            "expected_binding_digest != authorization.binding_digest"
        )
    if exp_authz_digest != authorization["authorization_digest"]:
        raise FlutterExecutionAuthorizationError(
            "expected_authorization_digest != "
            "authorization.authorization_digest"
        )

    # 4. Top-level authorization_digest recompute. Tampering any
    #    top-level field invalidates this digest; a coordinated attacker
    #    who recomputes it is still rejected by the out-of-band
    #    expected digest comparison above.
    recomputed_top_digest = _compute_authorization_digest(
        {k: v for k, v in authorization.items() if k != "authorization_digest"}
    )
    if recomputed_top_digest != authorization["authorization_digest"]:
        raise FlutterExecutionAuthorizationError(
            "authorization_digest does not equal recomputed digest"
        )

    # 5. Re-attest the embedded verified binding through the shared
    #    verify_binding. This catches any embedded binding tamper
    #    (request, plan, step, argv, cwd, timeout, primitive id/sha,
    #    manifest path/sha, descriptor, capsule, preflight, ...).
    binding_module = _load_binding_module()
    embedded_binding = authorization["verified_binding"]
    if not _is_canonical_json_suitable(embedded_binding):
        raise FlutterExecutionAuthorizationError(
            "verified_binding: not canonical-JSON suitable (NaN/Infinity/"
            "non-JSON value present)"
        )
    verify_report = binding_module.verify_binding(embedded_binding)
    if verify_report["binding_digest"] != authorization["binding_digest"]:
        raise FlutterExecutionAuthorizationError(
            "verified_binding binding_digest != authorization.binding_digest"
        )
    if (
        verify_report["selection_manifest_sha256"]
        != authorization["selection_manifest_sha256"]
    ):
        raise FlutterExecutionAuthorizationError(
            "verified_binding manifest sha != authorization manifest sha"
        )
    if (
        embedded_binding["selection_manifest_path"]
        != authorization["selection_manifest_path"]
    ):
        raise FlutterExecutionAuthorizationError(
            "verified_binding manifest path != authorization manifest path"
        )

    # 6. Recompute every per-step authorization from the embedded
    #    binding's plan steps. This re-hashes the current interpreter
    #    and primitive script bytes (TOCTOU defence), re-validates
    #    argv[0]/argv[1] canonical/regular/non-symlink, and requires
    #    exact equality with the candidate step_authorizations.
    recomputed_steps = _compute_step_authorizations(embedded_binding)
    candidate_steps = authorization["step_authorizations"]
    if len(recomputed_steps) != len(candidate_steps):
        raise FlutterExecutionAuthorizationError(
            f"step_authorizations count mismatch: "
            f"recomputed={len(recomputed_steps)} "
            f"candidate={len(candidate_steps)}"
        )
    for i, (recomputed, candidate) in enumerate(
        zip(recomputed_steps, candidate_steps)
    ):
        if recomputed != candidate:
            raise FlutterExecutionAuthorizationError(
                f"step_authorizations[{i}]: recomputed != candidate "
                f"(step reorder/add/delete/duplicate/field tamper, "
                f"executable/script digest drift, or path/cwd/timeout/"
                f"argv tamper)"
            )

    # 7. Return the exact verification report.
    return {
        "ok": True,
        "kind": KIND_AUTHZ_VERIFY,
        "schema_version": SCHEMA_VERSION,
        "platform_id": authorization["platform_id"],
        "operation_id": authorization["operation_id"],
        "port_id": authorization["port_id"],
        "binding_digest": authorization["binding_digest"],
        "selection_manifest_sha256": authorization["selection_manifest_sha256"],
        "authorization_digest": authorization["authorization_digest"],
        "execution_nonce": authorization["execution_nonce"],
    }


def verify_authorization(
    authorization: dict[str, Any],
    *,
    expected_manifest_path: Any,
    expected_manifest_sha256: Any,
    expected_binding_digest: Any,
    expected_authorization_digest: Any,
) -> dict[str, Any]:
    """Verify a ``icp.flutter-execution-authorization-candidate`` envelope.

    Requires all four trusted expected values:
    ``expected_manifest_path``, ``expected_manifest_sha256``,
    ``expected_binding_digest``, and ``expected_authorization_digest``.
    None may default, be inferred from the untrusted document, or be
    optional.

    Performs strict shape/literal/digest validation; cross-checks every
    expected value against the authorization; recomputes the top-level
    authorization digest; re-attests the embedded verified binding
    through the shared :func:`flutter_execution_binding_v1.verify_binding`;
    and recomputes every per-step authorization from the embedded
    binding's plan steps (re-hashing current interpreter and primitive
    script bytes). Requires exact equality at every stage.

    A coordinated attacker who rewrites workspace files and recomputes
    every in-document digest is still rejected by the unchanged
    out-of-band expected authorization digest.

    This slice executes no operation-plan command and consumes no
    nonce. Re-attesting the embedded binding through
    :func:`flutter_execution_binding_v1.verify_binding` does re-run the
    fixed read-only Flutter project preflight
    ``[resolved_flutter, "--version", "--machine"]`` (``shell=False``),
    the one transitive child process owned by the shared binding
    verifier's preflight module; this call can fail if that fixed
    preflight fails.

    P2e2b must call this function immediately before any spawn,
    atomically claim the recorded nonce against the supervisor-held
    expected authorization digest, and re-check executable and
    primitive-script bytes/paths immediately before each exact argv
    spawn. A normal path-based spawn still retains a small
    check-to-exec race after these checks; this slice alone does
    **not** eliminate that verify-to-spawn TOCTOU window.

    Returns the canonical verification report. Raises
    :class:`FlutterExecutionAuthorizationError` on any failure.
    """
    try:
        return _verify_authorization_impl(
            authorization,
            expected_manifest_path=expected_manifest_path,
            expected_manifest_sha256=expected_manifest_sha256,
            expected_binding_digest=expected_binding_digest,
            expected_authorization_digest=expected_authorization_digest,
        )
    except FlutterExecutionAuthorizationError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise FlutterExecutionAuthorizationError(
            f"verify_authorization raised {type(exc).__name__}"
        ) from exc
