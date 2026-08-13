#!/usr/bin/env python3
"""ICP P2e1 shared frozen selection-manifest verifier (read-only).

This module is the read-only re-attestor for the existing frozen
``selection-manifest.json`` produced by
``freeze_selection_manifest.freeze_selection_manifest``. It is shared by
every later platform execution binding (P2e1 Flutter, future Vue) so the
frozen manifest is re-attested exactly once through the freezer's own
canonical bytes / current registry/profile/rules/runtime-script digests.

Public Python API (no CLI, no executor, no writes):

* ``verify(manifest_path: str | os.PathLike[str]) -> dict[str, Any]``

Only ``verify`` plus a module-local typed exception
(:class:`SelectionManifestVerifyError`) may be public.

Validation order (hard):

1. Validate the supplied path before reading: absolute, lexically
   normalized, existing non-symlink regular file; reject any symlinked
   path component and path-resolution identity change. Bound size to
   8 MiB.
2. Read strict UTF-8 JSON object with duplicate-key rejection. Generic
   failures expose stable type-only messages through the local
   exception; no arbitrary exception text, secrets, or traceback.
3. Require exact frozen-manifest top-level shape, exact ``resolved``
   shape, exact candidate evidence shape, strict scalar types
   (``bool`` is never an ``int``), ``actual_batch_size == len(candidates)``,
   nonempty unique titles, unique positive row indexes, candidate status
   exactly empty, and nonempty design URLs. Reuses the existing
   syntax-only design-locator validation from ``preflight_selection``
   (no network).
4. Load only the fixed current registry with ``icp_common.load_registries()``.
5. Call ``freeze_selection_manifest.build_manifest_payload(...)`` with the
   document's exact ``resolved``, ``candidates``, ``batch_id``, and
   current registries. Require the recomputed payload to equal the
   decoded document and the recomputed canonical bytes to equal the
   file bytes exactly. This re-attests current registry/profile/rules/
   runtime-script digests and rejects noncanonical JSON, extra/missing/
   tampered fields, or current-source drift without duplicating the
   freezer's digest logic.
6. Require the supplied path to equal the recomputed exact
   ``<run_root>/selection-manifest.json``; require recomputed
   project/state/run roots to be absolute canonical no-symlink paths
   with ordinary directory ownership. Do not require task CSV bytes or
   row status to remain unchanged; the manifest freezes path/evidence,
   while claim legitimately changes the external CSV after freeze.
7. Return a fresh exact report.

Locked boundaries:

* Read-only. No write, no mkdir, no temp file, no symlink create, no
  claim, no writeback, no registry mutation.
* Stdlib only. No subprocess, shell, ``os.system``, ``os.popen``,
  network client, credential access, or arbitrary exception text.
* Production code derives the ICP root, scripts dir, verifier path, and
  registry path only from this module's installed file location and the
  fixed ``icp_common`` loader. No public override is exposed for skill
  root, manifest path, registry path, command, executable, script,
  interpreter, environment, argv, or activation.
* The verifier never imports, reads, executes, or follows a symlink
  into sibling ``iff/``.
"""

from __future__ import annotations

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
KIND_VERIFY = "icp.selection-manifest-verify.v1"

# Local error code (does not extend icp_common.ALL_ERROR_CODES).
CODE = "selection_manifest_verify_failed"

# Frozen top-level manifest shape (must match the freezer's payload exactly).
_MANIFEST_KIND = "icp.selection_manifest.v1"
_MANIFEST_SCHEMA_VERSION = 1
_MANIFEST_FILENAME = "selection-manifest.json"

_MAX_MANIFEST_BYTES = 8 * 1024 * 1024  # 8 MiB ceiling

# Exact no-whitespace ``batch_id`` grammar, enforced as a whole-string
# contract. This mirrors the producer's documented grammar
# ``^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$`` but is checked independently with
# :meth:`re.Pattern.fullmatch` (NOT :meth:`re.Pattern.match`): Python's
# ``$`` anchor may match before a final trailing newline, so
# ``re.match(r'...$')`` would accept a value ending in ``\n``. The
# producer enforces the same whole-string contract at its own input
# boundary; this independent check is defence-in-depth so a tampered
# manifest (canonical bytes rewritten by an attacker) is still rejected
# even if the producer's enforcement were ever weakened.
# ``fullmatch`` is the exact whole-string contract.
_BATCH_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")

_EXPECTED_TOP_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "batch_id",
        "resolved",
        "registry_digest",
        "selected_profile_digest",
        "rules_digest",
        "runtime_script_digests",
        "capabilities",
        "actual_batch_size",
        "candidates",
        "state_root",
        "run_root",
    }
)

_EXPECTED_RESOLVED_KEYS = frozenset(
    {
        "task_source",
        "task_ref",
        "design_source",
        "platform",
        "profile",
        "project_root",
    }
)

_EXPECTED_CANDIDATE_KEYS = frozenset(
    {
        "row_index",
        "title",
        "status",
        "design_url",
    }
)


class SelectionManifestVerifyError(Exception):
    """A local selection-manifest verification failure.

    Raised for any path/encoding/shape/digest/root mismatch. Generic
    failures are converted at the public API boundary to instances of
    this class whose message exposes the original exception's type name
    only; arbitrary exception text is never leaked.
    """


# ---------------------------------------------------------------------------
# Fixed production paths derived from this module's installed location.
# Accepts NO override; this is the runtime surface.
# ---------------------------------------------------------------------------

_ICP_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = Path(__file__).resolve().parent
_COMMON_PATH = _SCRIPTS_DIR / "icp_common.py"
_FREEZE_PATH = _SCRIPTS_DIR / "freeze_selection_manifest.py"
_PREFLIGHT_PATH = _SCRIPTS_DIR / "preflight_selection.py"


# ---------------------------------------------------------------------------
# Lazy module loaders (no sys.path mutation, no package import).
# ---------------------------------------------------------------------------


_COMMON_MODULE: Any = None
_FREEZE_MODULE: Any = None
_PREFLIGHT_MODULE: Any = None


def _load_module_by_path(name: str, path: Path):
    """Load ``path`` as a module under ``name`` without touching sys.path."""
    try:
        if path.is_symlink():
            raise SelectionManifestVerifyError(f"refusing symlink module: {path}")
        st = path.lstat()
    except OSError as exc:
        raise SelectionManifestVerifyError(
            f"cannot lstat module {path}: {type(exc).__name__}"
        ) from exc
    if not stat.S_ISREG(st.st_mode):
        raise SelectionManifestVerifyError(f"module not a regular file: {path}")
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise SelectionManifestVerifyError(f"cannot load module spec: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_common_module():
    global _COMMON_MODULE
    if _COMMON_MODULE is None:
        _COMMON_MODULE = _load_module_by_path("icp_common_p2e1_verify", _COMMON_PATH)
    return _COMMON_MODULE


def _load_freeze_module():
    global _FREEZE_MODULE
    if _FREEZE_MODULE is None:
        _FREEZE_MODULE = _load_module_by_path(
            "freeze_selection_manifest_p2e1_verify", _FREEZE_PATH
        )
    return _FREEZE_MODULE


def _load_preflight_module():
    global _PREFLIGHT_MODULE
    if _PREFLIGHT_MODULE is None:
        _PREFLIGHT_MODULE = _load_module_by_path(
            "preflight_selection_p2e1_verify", _PREFLIGHT_PATH
        )
    return _PREFLIGHT_MODULE


# ---------------------------------------------------------------------------
# Canonical JSON / digest helpers (re-use the common module's encoder).
# ---------------------------------------------------------------------------


def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    common = _load_common_module()
    return common.canonical_json_bytes(payload)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_sha256_hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value.islower()
        and all(c in "0123456789abcdef" for c in value)
    )


def _is_labeled_sha256(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    if not value.startswith("sha256:"):
        return False
    return _is_sha256_hex(value[len("sha256:"):])

# ---------------------------------------------------------------------------
# Strict JSON decode (UTF-8, duplicate-key rejection, non-object root).
# ---------------------------------------------------------------------------


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    for key, _value in pairs:
        if key in seen:
            raise SelectionManifestVerifyError(f"duplicate JSON key: {key!r}")
        seen.add(key)
    return dict(pairs)


def _decode_json_strict(raw: bytes, role: str) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SelectionManifestVerifyError(
            f"{role}: not UTF-8: {type(exc).__name__}"
        ) from exc
    decoder = json.JSONDecoder(object_pairs_hook=_reject_duplicate_keys)
    try:
        obj = decoder.decode(text)
    except SelectionManifestVerifyError:
        raise
    except json.JSONDecodeError as exc:
        raise SelectionManifestVerifyError(f"{role}: not valid JSON") from exc
    if not isinstance(obj, dict):
        raise SelectionManifestVerifyError(
            f"{role}: root must be a JSON object, got {type(obj).__name__}"
        )
    return obj


# ---------------------------------------------------------------------------
# Path validation: absolute, lexically normalized, non-symlink regular
# file, no symlinked component, strict-resolve identity match, bounded.
# ---------------------------------------------------------------------------


def _validate_path(manifest_path: str | os.PathLike[str]) -> Path:
    if isinstance(manifest_path, (bytes, bytearray)):
        raise SelectionManifestVerifyError(
            "manifest_path: must be str or os.PathLike, got bytes"
        )
    if not isinstance(manifest_path, (str, os.PathLike)):
        raise SelectionManifestVerifyError(
            f"manifest_path: must be str or os.PathLike, got "
            f"{type(manifest_path).__name__}"
        )
    try:
        root_str = os.fspath(manifest_path)
    except TypeError as exc:
        raise SelectionManifestVerifyError(
            f"manifest_path: cannot coerce to path: {type(manifest_path).__name__}"
        ) from exc
    if not isinstance(root_str, str):
        raise SelectionManifestVerifyError(
            "manifest_path: must be a text path, got bytes"
        )
    raw = Path(root_str)
    if not raw.is_absolute():
        raise SelectionManifestVerifyError(
            f"manifest_path: not absolute: {root_str!r}"
        )
    if any(part == ".." for part in raw.parts):
        raise SelectionManifestVerifyError(
            f"manifest_path: contains '..': {root_str!r}"
        )
    if os.path.normpath(root_str) != root_str:
        raise SelectionManifestVerifyError(
            f"manifest_path: not lexically normalized: {root_str!r}"
        )
    # Leaf must not be a symlink; reject non-regular file.
    try:
        if raw.is_symlink():
            raise SelectionManifestVerifyError(
                f"manifest_path: refusing symlink: {raw}"
            )
    except OSError as exc:
        raise SelectionManifestVerifyError(
            f"manifest_path: cannot lstat: {type(exc).__name__}"
        ) from exc
    try:
        st = raw.lstat()
    except FileNotFoundError as exc:
        raise SelectionManifestVerifyError(
            f"manifest_path: not found: {raw}"
        ) from exc
    except OSError as exc:
        raise SelectionManifestVerifyError(
            f"manifest_path: cannot lstat: {type(exc).__name__}"
        ) from exc
    if not stat.S_ISREG(st.st_mode):
        raise SelectionManifestVerifyError(
            f"manifest_path: not a regular file: {raw}"
        )
    # Bound size to 8 MiB before reading.
    if st.st_size > _MAX_MANIFEST_BYTES:
        raise SelectionManifestVerifyError(
            f"manifest_path: size {st.st_size} exceeds ceiling {_MAX_MANIFEST_BYTES}"
        )
    # Strict-resolve the leaf and require identity. Because the leaf is
    # already a non-symlink regular file, a divergence here means a
    # symlinked ancestor redirected the path (and is rejected).
    try:
        resolved = raw.resolve(strict=True)
    except FileNotFoundError as exc:
        raise SelectionManifestVerifyError(
            f"manifest_path: missing after resolve: {raw}"
        ) from exc
    except RuntimeError as exc:
        raise SelectionManifestVerifyError(
            f"manifest_path: resolve loop: {type(exc).__name__}"
        ) from exc
    except OSError as exc:
        raise SelectionManifestVerifyError(
            f"manifest_path: resolve failed: {type(exc).__name__}"
        ) from exc
    if resolved != raw:
        raise SelectionManifestVerifyError(
            f"manifest_path: supplied path differs from strict resolve "
            f"(symlinked ancestor): {raw} -> {resolved}"
        )
    return resolved


# ---------------------------------------------------------------------------
# Shape validation: top-level, resolved, candidates, scalar types.
# ---------------------------------------------------------------------------


def _require_str(value: Any, role: str) -> str:
    if not isinstance(value, str):
        raise SelectionManifestVerifyError(
            f"{role}: must be a string, got {type(value).__name__}"
        )
    return value


def _require_bool(value: Any, role: str) -> bool:
    # bool is a subclass of int in Python; require the literal True/False
    # so a numeric 0/1 cannot impersonate a boolean.
    if value is True or value is False:
        return value
    raise SelectionManifestVerifyError(
        f"{role}: must be a bool, got {type(value).__name__}"
    )


def _require_int(value: Any, role: str) -> int:
    # Explicitly reject bool (a subclass of int) so True/False cannot
    # impersonate an integer count.
    if isinstance(value, bool):
        raise SelectionManifestVerifyError(
            f"{role}: must be an int, got bool"
        )
    if not isinstance(value, int):
        raise SelectionManifestVerifyError(
            f"{role}: must be an int, got {type(value).__name__}"
        )
    return value


def _validate_top_level_shape(doc: dict[str, Any]) -> None:
    keys = set(doc.keys())
    if keys != _EXPECTED_TOP_KEYS:
        extra = sorted(keys - _EXPECTED_TOP_KEYS)
        missing = sorted(_EXPECTED_TOP_KEYS - keys)
        raise SelectionManifestVerifyError(
            f"manifest top-level keys mismatch: "
            f"extra={extra} missing={missing}"
        )
    if doc["kind"] != _MANIFEST_KIND:
        raise SelectionManifestVerifyError(
            f"manifest kind mismatch: {doc['kind']!r}"
        )
    if _require_int(doc["schema_version"], "schema_version") != _MANIFEST_SCHEMA_VERSION:
        raise SelectionManifestVerifyError(
            f"manifest schema_version mismatch: {doc['schema_version']!r}"
        )
    # Independently enforce the exact no-whitespace ``batch_id`` grammar
    # as a whole-string contract (defence-in-depth). The producer now
    # enforces the same contract at its own input boundary, but this
    # independent check rejects a tampered manifest whose canonical bytes
    # were rewritten by an attacker. ``re.match(r'...$')`` accepts a
    # trailing newline; ``fullmatch`` does not.
    _require_str(doc["batch_id"], "batch_id")
    if not _BATCH_ID_RE.fullmatch(doc["batch_id"]):
        raise SelectionManifestVerifyError(
            f"manifest batch_id must match {str(_BATCH_ID_RE.pattern)!r} "
            f"exactly, got {doc['batch_id']!r}"
        )
    if not isinstance(doc["resolved"], dict):
        raise SelectionManifestVerifyError(
            f"manifest resolved must be an object, got {type(doc['resolved']).__name__}"
        )
    if not _is_labeled_sha256(doc["registry_digest"]):
        raise SelectionManifestVerifyError("manifest registry_digest malformed")
    if not _is_labeled_sha256(doc["selected_profile_digest"]):
        raise SelectionManifestVerifyError(
            "manifest selected_profile_digest malformed"
        )
    if not _is_labeled_sha256(doc["rules_digest"]):
        raise SelectionManifestVerifyError("manifest rules_digest malformed")
    rt = doc["runtime_script_digests"]
    if not isinstance(rt, dict) or not rt:
        raise SelectionManifestVerifyError(
            "manifest runtime_script_digests must be a non-empty object"
        )
    for k, v in rt.items():
        if not isinstance(k, str) or not k:
            raise SelectionManifestVerifyError(
                "manifest runtime_script_digests key malformed"
            )
        if not _is_labeled_sha256(v):
            raise SelectionManifestVerifyError(
                f"manifest runtime_script_digests[{k!r}] malformed"
            )
    caps = doc["capabilities"]
    if not isinstance(caps, dict) or not caps:
        raise SelectionManifestVerifyError(
            "manifest capabilities must be a non-empty object"
        )
    for k, v in caps.items():
        if not isinstance(k, str) or not k:
            raise SelectionManifestVerifyError(
                "manifest capabilities key malformed"
            )
        if not isinstance(v, str) or v == "":
            raise SelectionManifestVerifyError(
                f"manifest capabilities[{k!r}] must be a non-empty string"
            )
    _require_int(doc["actual_batch_size"], "actual_batch_size")
    if not isinstance(doc["candidates"], list):
        raise SelectionManifestVerifyError(
            f"manifest candidates must be a list, got "
            f"{type(doc['candidates']).__name__}"
        )
    _require_str(doc["state_root"], "state_root")
    _require_str(doc["run_root"], "run_root")


def _validate_resolved_shape(resolved: dict[str, Any]) -> None:
    keys = set(resolved.keys())
    if keys != _EXPECTED_RESOLVED_KEYS:
        extra = sorted(keys - _EXPECTED_RESOLVED_KEYS)
        missing = sorted(_EXPECTED_RESOLVED_KEYS - keys)
        raise SelectionManifestVerifyError(
            f"manifest resolved keys mismatch: extra={extra} missing={missing}"
        )
    for key in _EXPECTED_RESOLVED_KEYS:
        _require_str(resolved[key], f"resolved.{key}")


def _validate_resolved_against_registry(
    resolved: dict[str, Any], registries: dict[str, Any]
) -> None:
    """Cross-check the resolved platform/profile against the current fixed
    registry. The platform must be registered and the resolved profile
    must equal the platform's selected ``default_profile`` (the exact
    nonempty selected current profile).

    This is a structural current-registry binding. It does not detect an
    arbitrary unsigned rewrite of candidate values that produces another
    structurally valid frozen manifest: distinguishing that requires the
    trusted orchestrator to retain the expected manifest SHA-256 out of
    band. The Flutter binding records the exact SHA; P2e2/orchestrator
    must compare it against the expected value before executing any plan.
    """
    platform = resolved["platform"]
    profile = resolved["profile"]
    platforms = registries.get("platforms", {})
    if not isinstance(platforms, dict) or platform not in platforms:
        raise SelectionManifestVerifyError(
            f"resolved.platform {platform!r} not in current registry"
        )
    entry = platforms[platform]
    if not isinstance(entry, dict):
        raise SelectionManifestVerifyError(
            f"registry platform entry {platform!r} not an object"
        )
    default_profile = entry.get("default_profile")
    if not isinstance(default_profile, str) or not default_profile:
        raise SelectionManifestVerifyError(
            f"registry platform {platform!r} has no selected default_profile"
        )
    if profile != default_profile:
        raise SelectionManifestVerifyError(
            f"resolved.profile {profile!r} must equal selected "
            f"default_profile {default_profile!r}"
        )


def _validate_candidates(candidates: list[dict[str, Any]], preflight_module) -> None:
    titles: set[str] = set()
    row_indexes: set[int] = set()
    for index, cand in enumerate(candidates):
        if not isinstance(cand, dict):
            raise SelectionManifestVerifyError(
                f"candidate[{index}] not an object"
            )
        keys = set(cand.keys())
        if keys != _EXPECTED_CANDIDATE_KEYS:
            extra = sorted(keys - _EXPECTED_CANDIDATE_KEYS)
            missing = sorted(_EXPECTED_CANDIDATE_KEYS - keys)
            raise SelectionManifestVerifyError(
                f"candidate[{index}] keys mismatch: extra={extra} missing={missing}"
            )
        row_index = _require_int(cand["row_index"], f"candidate[{index}].row_index")
        if row_index <= 0:
            raise SelectionManifestVerifyError(
                f"candidate[{index}].row_index must be positive: {row_index!r}"
            )
        if row_index in row_indexes:
            raise SelectionManifestVerifyError(
                f"candidate[{index}].row_index duplicate: {row_index!r}"
            )
        row_indexes.add(row_index)
        title = _require_str(cand["title"], f"candidate[{index}].title")
        if title == "":
            raise SelectionManifestVerifyError(
                f"candidate[{index}].title must be non-empty"
            )
        if title in titles:
            raise SelectionManifestVerifyError(
                f"candidate[{index}].title duplicate: {title!r}"
            )
        titles.add(title)
        status = _require_str(cand["status"], f"candidate[{index}].status")
        if status != "":
            raise SelectionManifestVerifyError(
                f"candidate[{index}].status must be exactly empty: {status!r}"
            )
        design_url = _require_str(cand["design_url"], f"candidate[{index}].design_url")
        if design_url == "":
            raise SelectionManifestVerifyError(
                f"candidate[{index}].design_url must be non-empty"
            )
        # Reuse the existing syntax-only design-locator validation. It
        # is a read-only check; no network.
        result = preflight_module.preflight_design_locator(design_url)
        if not result.ok:
            raise SelectionManifestVerifyError(
                f"candidate[{index}].design_url malformed: {design_url!r}"
            )


# ---------------------------------------------------------------------------
# Root validation: absolute canonical no-symlink ordinary directories.
# ---------------------------------------------------------------------------


def _check_nonsymlink_dir(path: Path, role: str) -> None:
    try:
        if path.is_symlink():
            raise SelectionManifestVerifyError(f"{role}: refusing symlink: {path}")
        st = path.stat()
    except FileNotFoundError as exc:
        raise SelectionManifestVerifyError(f"{role}: not found: {path}") from exc
    except OSError as exc:
        raise SelectionManifestVerifyError(
            f"{role}: cannot stat: {type(exc).__name__}"
        ) from exc
    if not stat.S_ISDIR(st.st_mode):
        raise SelectionManifestVerifyError(f"{role}: not a directory: {path}")


def _validate_root_path(value: str, role: str) -> Path:
    """Validate an absolute, lexically normalized, non-symlink real
    directory. Returns the resolved :class:`Path`."""
    if not isinstance(value, str):
        raise SelectionManifestVerifyError(
            f"{role}: must be a string, got {type(value).__name__}"
        )
    raw = Path(value)
    if not raw.is_absolute():
        raise SelectionManifestVerifyError(f"{role}: not absolute: {value!r}")
    if any(part == ".." for part in raw.parts):
        raise SelectionManifestVerifyError(f"{role}: contains '..': {value!r}")
    if os.path.normpath(value) != value:
        raise SelectionManifestVerifyError(f"{role}: not lexically normalized: {value!r}")
    try:
        resolved = raw.resolve(strict=True)
    except FileNotFoundError as exc:
        raise SelectionManifestVerifyError(f"{role}: does not exist: {value!r}") from exc
    except RuntimeError as exc:
        raise SelectionManifestVerifyError(
            f"{role}: resolve loop: {type(exc).__name__}"
        ) from exc
    except OSError as exc:
        raise SelectionManifestVerifyError(
            f"{role}: resolve failed: {type(exc).__name__}"
        ) from exc
    if resolved != raw:
        raise SelectionManifestVerifyError(
            f"{role}: supplied path differs from strict resolve "
            f"(symlinked root or ancestor)"
        )
    _check_nonsymlink_dir(resolved, role)
    return resolved


# ---------------------------------------------------------------------------
# Public verifier.
# ---------------------------------------------------------------------------


def _verify_impl(manifest_path: str | os.PathLike[str]) -> dict[str, Any]:
    # 1. Path validation (before any read).
    canonical_path = _validate_path(manifest_path)

    # 2. Read + strict decode.
    try:
        raw_bytes = canonical_path.read_bytes()
    except OSError as exc:
        raise SelectionManifestVerifyError(
            f"manifest_path: cannot read: {type(exc).__name__}"
        ) from exc
    if len(raw_bytes) > _MAX_MANIFEST_BYTES:
        raise SelectionManifestVerifyError(
            f"manifest_path: bytes {len(raw_bytes)} exceed ceiling {_MAX_MANIFEST_BYTES}"
        )
    doc = _decode_json_strict(raw_bytes, "selection-manifest.json")

    # 3. Shape validation.
    _validate_top_level_shape(doc)
    _validate_resolved_shape(doc["resolved"])
    preflight_module = _load_preflight_module()
    _validate_candidates(doc["candidates"], preflight_module)

    # Candidate count must equal actual_batch_size. (Defence-in-depth;
    # the canonical-bytes comparison below would also catch a mismatch
    # for an attacker-supplied doc.)
    if doc["actual_batch_size"] != len(doc["candidates"]):
        raise SelectionManifestVerifyError(
            f"manifest actual_batch_size != len(candidates): "
            f"{doc['actual_batch_size']} != {len(doc['candidates'])}"
        )

    # 4. Load only the fixed current registry.
    common = _load_common_module()
    registries = common.load_registries()

    # Cross-check the resolved platform/profile against the current
    # registry before recomputing the payload (defence-in-depth; the
    # recompute below would also surface a platform mismatch via the
    # freezer's selected-profile digest, but the explicit check gives a
    # clear, stable error).
    _validate_resolved_against_registry(doc["resolved"], registries)

    # 5. Recompute the canonical payload through the freezer's source of
    # truth and require exact equality with the decoded document.
    freeze = _load_freeze_module()
    try:
        payload, state_root, run_root, encoded = freeze.build_manifest_payload(
            resolved_config=doc["resolved"],
            candidates=doc["candidates"],
            batch_id=doc["batch_id"],
            registries=registries,
        )
    except freeze.ManifestFreezeError as exc:
        raise SelectionManifestVerifyError(
            f"recompute failed: {exc.code}"
        ) from exc
    # Payload equality (dict-level). Dict equality is order-independent
    # but catches missing/extra/wrong-typed fields; the byte-level check
    # below catches non-canonical JSON.
    if payload != doc:
        raise SelectionManifestVerifyError(
            "recomputed payload does not equal decoded document"
        )
    if encoded != raw_bytes:
        raise SelectionManifestVerifyError(
            "recomputed canonical bytes do not equal file bytes"
        )

    # 6. Path identity: supplied path must equal <run_root>/selection-manifest.json.
    expected_manifest_path = Path(run_root) / _MANIFEST_FILENAME
    if canonical_path != expected_manifest_path:
        raise SelectionManifestVerifyError(
            f"manifest_path mismatch: got {canonical_path} "
            f"expected {expected_manifest_path}"
        )
    # Roots must be absolute canonical no-symlink ordinary directories.
    project_root = _validate_root_path(doc["resolved"]["project_root"], "resolved.project_root")
    state_root_path = _validate_root_path(str(state_root), "state_root")
    run_root_path = _validate_root_path(str(run_root), "run_root")
    # state_root must be a strict child of project_root; run_root must
    # be a strict child of state_root (no symlink escape).
    try:
        state_root_path.relative_to(project_root)
    except ValueError as exc:
        raise SelectionManifestVerifyError(
            "state_root is not contained in project_root"
        ) from exc
    try:
        run_root_path.relative_to(state_root_path)
    except ValueError as exc:
        raise SelectionManifestVerifyError(
            "run_root is not contained in state_root"
        ) from exc
    if state_root_path == project_root:
        raise SelectionManifestVerifyError("state_root must differ from project_root")
    if run_root_path == state_root_path:
        raise SelectionManifestVerifyError("run_root must differ from state_root")

    # 7. Build the exact report.
    manifest_sha = _sha256_bytes(raw_bytes)
    return {
        "kind": KIND_VERIFY,
        "schema_version": SCHEMA_VERSION,
        "batch_id": doc["batch_id"],
        "platform_id": doc["resolved"]["platform"],
        "profile_id": doc["resolved"]["profile"],
        "project_root": str(project_root),
        "state_root": str(state_root_path),
        "run_root": str(run_root_path),
        "manifest_path": str(canonical_path),
        "manifest_sha256": manifest_sha,
        "registry_digest": doc["registry_digest"],
        "selected_profile_digest": doc["selected_profile_digest"],
        "rules_digest": doc["rules_digest"],
        "actual_batch_size": doc["actual_batch_size"],
    }


def verify(manifest_path: str | os.PathLike[str]) -> dict[str, Any]:
    """Verify a frozen selection manifest at ``manifest_path``.

    Re-attests the current registry/profile/rules/runtime-script digests
    by recomputing the canonical payload through the freezer's source of
    truth and requiring byte-identical canonical bytes against the file
    bytes. Requires the supplied path to equal the recomputed exact
    ``<run_root>/selection-manifest.json`` and the recomputed roots to be
    absolute canonical no-symlink ordinary directories.

    Returns the canonical report (see module docstring). Raises
    :class:`SelectionManifestVerifyError` on any failure; generic
    exceptions are wrapped to type-only messages.
    """
    try:
        return _verify_impl(manifest_path)
    except SelectionManifestVerifyError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise SelectionManifestVerifyError(
            f"verify raised {type(exc).__name__}"
        ) from exc
