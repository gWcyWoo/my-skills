#!/usr/bin/env python3
"""ICP P2.5d Flutter merged-expectation provenance gate — v1.

This module is the single platform-origin gate step that P2.5d inserts
between the frozen ``merge_shared_expected.py`` capsule producer (step 0
of ``flutter.trace_harness.v1``) and the frozen
``gen_layout_trace_test.py`` capsule consumer (step 2). It is the only
new production file P2.5d adds.

The gate:

  1. derives ``ICP_ROOT``, the capsule scripts directory, the SharedCore
     directory, the vendor manifest path, and the fixed capsule
     verifier path ONLY from its installed ``__file__``;
  2. performs the established two-stage fixed verifier load +
     ``verify_skill(ICP_ROOT)`` pattern before trusting the capsule;
  3. strict-loads the fixed vendor manifest with duplicate-key
     rejection, finds exactly one ``merge_shared_expected.py`` record,
     recomputes the installed capsule file SHA-256, and requires
     equality with the manifest digest;
  4. validates ``run_root`` and every supplied absolute path
     (canonical, strictly below ``run_root``, current-owner, no
     symlink at any component, bounded regular input; permits only the
     absent ``shared_components_local`` leaf; validates output target
     safely);
  5. strict-decodes JSON with duplicate-key rejection and bounded
     UTF-8;
  6. fixed-loads both SharedCore modules
     (``expected_slots_projection_v1.py`` and
     ``merged_expectation_provenance_v1.py``) from sibling paths with
     no ``sys.path`` mutation and no bytecode emission;
  7. requires raw projection bytes equal
     ``build_projection_bytes(projection_doc)``;
  8. requires ``build_legacy_bytes(projection_doc)[0]`` byte-for-byte
     equals the raw ``page_canvas_expected`` bytes;
  9. requires frozen-merge canonical output bytes equal
     ``json.dumps(merged_doc, ensure_ascii=False, indent=2) + "\\n"``;
  10. requires merged top-level fields other than ``nodes`` equal the
      page legacy expected document, page node IDs form the exact
      prefix of merged node IDs, and every page node value is
      unchanged; derives shared node IDs as only the suffix;
  11. when local is absent, additionally requires the merged document
      equals the page expected document and shared node IDs are empty;
  12. computes SHA-256 over the actual raw bytes of projection,
      present local (or null), scene, and merged output;
  13. calls existing P2.5c ``build_provenance``,
      ``validate_provenance``, and ``build_provenance_bytes`` with the
      manifest-bound producer SHA and the page/shared/merged node IDs
      derived from the actual documents;
  14. atomically publishes canonical provenance bytes to
      ``provenance_out`` using a current-owner mode-0600 temp in the
      same safe directory, fsync file + directory, and atomic replace;
      safe reruns may replace a safe existing regular output;
  15. re-opens the published artifact, requires exact byte equality
      with what was written, strict-decodes, validates again, and
      requires canonical byte equality before success;
  16. emits only one deterministic sanitized JSON success summary;
      errors use one typed local exception and sanitized fixed-role/
      type output, no traceback, absolute path, raw bytes/content,
      arbitrary child error, environment, or secret.

CLI accepts EXACTLY seven flags, each once. There is no producer path,
SHA, manifest, capsule, command, executable, import, env, shell, URL,
or root override.

No subprocess. Standard library only. No iFF merge reimplementation.
The gate inherits the controlled-executor trust boundary: it does not
claim a cryptographic proof of which prior process wrote a file or a
file-swap detection before its own first read. That boundary is the
already-controlled executor's responsibility, documented in the P2.5d
reference.

CLI::

    python3 flutter_merged_expectation_provenance_gate_v1.py \\
        --run-root <absolute dir> \\
        --page-canvas-expected <absolute .expected.json> \\
        --page-canvas-projection <absolute .json> \\
        --shared-components-local <absolute .json, may not exist> \\
        --scene <absolute .json> \\
        --merged-expected <absolute .json> \\
        --provenance-out <absolute .json>
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

# Suppress bytecode emit so loading SharedCore / the verifier / the
# capsule manifest never litters __pycache__ under shared_core/.
sys.dont_write_bytecode = True  # noqa: Q000

__all__ = ["MergedExpectationGateError", "main"]

# ---------------------------------------------------------------------------
# Fixed production paths derived ONLY from this module's installed
# __file__. Accepts NO override.
# ---------------------------------------------------------------------------

_GATE_FILE = Path(__file__).resolve()
_GATE_DIR = _GATE_FILE.parent                       # icp/scripts/platforms
_ICP_ROOT = _GATE_FILE.parents[2]                    # icp/
_PLATFORMS_DIR = _GATE_DIR
_SHARED_CORE_DIR = _GATE_FILE.parents[1] / "shared_core"
_CAPSULE_SCRIPTS_DIR = _ICP_ROOT / "vendor" / "iff_v1" / "scripts"
_MANIFEST_PATH = _ICP_ROOT / "references" / "baselines" / "iff-v1-vendor.json"
_VERIFY_TOOL = _ICP_ROOT / "scripts" / "verify_vendor_iff_v1.py"
_PROJECTION_MODULE_PATH = _SHARED_CORE_DIR / "expected_slots_projection_v1.py"
_PROVENANCE_MODULE_PATH = _SHARED_CORE_DIR / "merged_expectation_provenance_v1.py"

# Fixed producer identifier recorded in every provenance document.
_KIND_PRODUCER = "iff-v1.merge_shared_expected"
_PRODUCER_PRIMITIVE_BASENAME = "merge_shared_expected.py"

# Bounded read maximum: 16 MiB per input/output file.
_MAX_FILE_BYTES = 16 * 1024 * 1024


class MergedExpectationGateError(Exception):
    """A local Flutter merged-expectation provenance gate failure.

    Raised for any path/validation/canonical/parity/publish failure.
    Generic failures are converted at the public boundary
    (:func:`main`) to instances of this class whose message exposes
    only fixed role/type-safe text; arbitrary exception text, file
    contents, supplied paths, and tracebacks are never leaked.
    """


# ---------------------------------------------------------------------------
# Capsule verification (two-stage fixed verifier load).
# ---------------------------------------------------------------------------

_VERIFY_MODULE: Any = None


def _load_verify_module():
    """Load ``verify_vendor_iff_v1`` by file path (no sys.path
    mutation). Two-stage: the module must load successfully BEFORE its
    ``CapsuleIntegrityError`` class is trusted for isinstance-based
    classification of any later failure.
    """
    global _VERIFY_MODULE
    if _VERIFY_MODULE is None:
        _check_regular_nonsymlink(_VERIFY_TOOL, "verify_vendor_iff_v1.py")
        spec = importlib.util.spec_from_file_location(
            "p25d_verify_vendor_iff_v1", str(_VERIFY_TOOL)
        )
        if spec is None or spec.loader is None:
            raise MergedExpectationGateError(
                "cannot load verify_vendor_iff_v1 module spec"
            )
        module = importlib.util.module_from_spec(spec)
        sys.modules["p25d_verify_vendor_iff_v1"] = module
        spec.loader.exec_module(module)
        _VERIFY_MODULE = module
    return _VERIFY_MODULE


def _verify_capsule() -> dict[str, Any]:
    """Verify the installed vendored capsule via the P2a runtime gate.

    Returns the canonical capsule-success payload. Any integrity
    violation surfaces as a :class:`MergedExpectationGateError`.
    """
    # Stage 1: load the fixed verifier module by file path. Any
    # exception here is untrusted (the verifier's typed error class
    # is not yet loaded).
    try:
        verifier_module = _load_verify_module()
    except MergedExpectationGateError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise MergedExpectationGateError(
            f"capsule verifier load raised {type(exc).__name__}"
        ) from exc

    # Stage 2: the fixed verifier module loaded successfully. Only now
    # is its ``CapsuleIntegrityError`` class trustworthy for
    # isinstance-based classification.
    try:
        return verifier_module.verify_skill(_ICP_ROOT)
    except verifier_module.CapsuleIntegrityError as exc:
        raise MergedExpectationGateError(
            f"capsule verification failed: {exc}"
        ) from exc
    except MergedExpectationGateError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise MergedExpectationGateError(
            f"capsule verification raised {type(exc).__name__}"
        ) from exc


# ---------------------------------------------------------------------------
# Manifest load + shape validation + producer SHA lookup.
# ---------------------------------------------------------------------------


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    for key, _value in pairs:
        if key in seen:
            raise MergedExpectationGateError("duplicate JSON key in manifest")
        seen.add(key)
    return dict(pairs)


def _decode_json_strict(raw: bytes, role: str) -> Any:
    """Decode ``raw`` as strict UTF-8 JSON with duplicate-key rejection.

    Raises :class:`MergedExpectationGateError` (type-only message) on
    any failure. The ``role`` is used only to disambiguate the failure;
    no raw input is included in the message.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MergedExpectationGateError(
            f"{role}: not UTF-8: {type(exc).__name__}"
        ) from exc
    try:
        return json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except MergedExpectationGateError:
        raise
    except ValueError as exc:
        raise MergedExpectationGateError(f"{role}: not valid JSON") from exc


def _is_sha256_hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value.islower()
        and all(c in "0123456789abcdef" for c in value)
    )


def _is_safe_basename(name: Any) -> bool:
    if not isinstance(name, str) or not name:
        return False
    if "/" in name or "\\" in name or name in {".", ".."} or "\x00" in name:
        return False
    if name != os.path.basename(name):
        return False
    return True


def _check_regular_nonsymlink(path: Path, role: str) -> None:
    """Require ``path`` to exist, be a regular file, and not be a symlink."""
    try:
        if path.is_symlink():
            raise MergedExpectationGateError(f"{role}: refusing symlink")
        st = path.lstat()
    except FileNotFoundError as exc:
        raise MergedExpectationGateError(f"{role}: not found") from exc
    except OSError as exc:
        raise MergedExpectationGateError(
            f"{role}: cannot lstat: {type(exc).__name__}"
        ) from exc
    if not stat.S_ISREG(st.st_mode):
        raise MergedExpectationGateError(f"{role}: not a regular file")


def _load_manifest() -> dict[str, Any]:
    _check_regular_nonsymlink(_MANIFEST_PATH, "iff-v1-vendor.json")
    manifest = _decode_json_strict(
        _MANIFEST_PATH.read_bytes(), "iff-v1-vendor.json"
    )
    if not isinstance(manifest, dict):
        raise MergedExpectationGateError("manifest root not an object")
    if manifest.get("kind") != "icp.iff-v1-vendor-capsule":
        raise MergedExpectationGateError("manifest kind not canonical")
    if manifest.get("schema_version") != 1:
        raise MergedExpectationGateError("manifest schema_version not canonical")
    if manifest.get("capsule_root") != "vendor/iff_v1":
        raise MergedExpectationGateError("manifest capsule_root not canonical")
    scripts = manifest.get("scripts")
    if not isinstance(scripts, list) or not scripts:
        raise MergedExpectationGateError("manifest scripts missing/empty")
    return manifest


def _manifest_merge_producer_sha(manifest: dict[str, Any]) -> str:
    """Find exactly one ``merge_shared_expected.py`` entry in the
    manifest's scripts list, require its SHA-256 is well-formed, and
    require that the installed capsule file's recomputed SHA-256
    matches the manifest digest. Returns the manifest digest.
    """
    matches = [
        e for e in manifest["scripts"]
        if isinstance(e, dict) and e.get("name") == _PRODUCER_PRIMITIVE_BASENAME
    ]
    if len(matches) != 1:
        raise MergedExpectationGateError(
            "manifest does not contain exactly one "
            f"{_PRODUCER_PRIMITIVE_BASENAME!r} entry"
        )
    entry = matches[0]
    sha = entry.get("sha256")
    if not _is_sha256_hex(sha):
        raise MergedExpectationGateError(
            "manifest producer sha256 malformed"
        )
    # Recompute the installed capsule file SHA and require equality.
    capsule_path = _CAPSULE_SCRIPTS_DIR / _PRODUCER_PRIMITIVE_BASENAME
    _check_regular_nonsymlink(capsule_path, "producer capsule")
    try:
        actual = hashlib.sha256(capsule_path.read_bytes()).hexdigest()
    except OSError as exc:
        raise MergedExpectationGateError(
            f"producer capsule unreadable: {type(exc).__name__}"
        ) from exc
    if actual != sha:
        raise MergedExpectationGateError(
            "producer capsule sha256 mismatch (manifest vs installed)"
        )
    return sha


# ---------------------------------------------------------------------------
# Path / file validators (fail-closed, sanitized).
# ---------------------------------------------------------------------------


def _check_current_owner(st: os.stat_result, role: str) -> None:
    """Reject files not owned by the current effective user (Unix only)."""
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None:
        return  # non-portable
    try:
        if st.st_uid != geteuid():
            raise MergedExpectationGateError(
                f"{role}: not owned by current user"
            )
    except AttributeError:
        return


def _validate_abs_path(value: Any, role: str) -> Path:
    if not isinstance(value, str):
        raise MergedExpectationGateError(
            f"{role}: must be a string, got {type(value).__name__}"
        )
    if not os.path.isabs(value):
        raise MergedExpectationGateError(f"{role}: not absolute")
    if any(part == ".." for part in Path(value).parts):
        raise MergedExpectationGateError(f"{role}: contains '..'")
    if os.path.normpath(value) != value:
        raise MergedExpectationGateError(f"{role}: not lexically normalized")
    if "\\" in value:
        raise MergedExpectationGateError(f"{role}: contains backslash")
    if "\x00" in value:
        raise MergedExpectationGateError(f"{role}: contains NUL")
    if "://" in value:
        raise MergedExpectationGateError(f"{role}: URI scheme not allowed")
    return Path(value)


def _validate_run_root(value: Any) -> Path:
    raw = _validate_abs_path(value, "run_root")
    try:
        if raw.is_symlink():
            raise MergedExpectationGateError("run_root: refusing symlink")
        st = raw.lstat()
    except FileNotFoundError as exc:
        raise MergedExpectationGateError("run_root: not found") from exc
    except OSError as exc:
        raise MergedExpectationGateError(
            f"run_root: cannot lstat: {type(exc).__name__}"
        ) from exc
    if not stat.S_ISDIR(st.st_mode):
        raise MergedExpectationGateError("run_root: not a directory")
    _check_current_owner(st, "run_root")
    try:
        resolved = raw.resolve(strict=True)
    except FileNotFoundError as exc:
        raise MergedExpectationGateError("run_root: resolve failed") from exc
    except OSError as exc:
        raise MergedExpectationGateError(
            f"run_root: resolve failed: {type(exc).__name__}"
        ) from exc
    if resolved != raw:
        raise MergedExpectationGateError(
            "run_root: supplied path differs from strict resolve"
        )
    return resolved


def _walk_no_symlink_chain(rel_parts: tuple[str, ...], root: Path, role: str) -> Path:
    """Walk every component below ``root`` and require each to be a
    non-symlink. Returns the absolute leaf Path (the leaf need not
    exist; intermediate components must be directories)."""
    current = root
    last = len(rel_parts) - 1
    for index, part in enumerate(rel_parts):
        candidate = current / part
        try:
            if candidate.is_symlink():
                raise MergedExpectationGateError(
                    f"{role}: refusing symlinked component"
                )
        except OSError as exc:
            raise MergedExpectationGateError(
                f"{role}: cannot lstat: {type(exc).__name__}"
            ) from exc
        try:
            st = candidate.lstat()
        except FileNotFoundError:
            # Absent component from here onward. Nearest existing
            # ancestor is ``current`` (already verified). All further
            # components are absent by definition.
            return candidate
        except OSError as exc:
            raise MergedExpectationGateError(
                f"{role}: cannot stat: {type(exc).__name__}"
            ) from exc
        if index < last:
            if not stat.S_ISDIR(st.st_mode):
                raise MergedExpectationGateError(
                    f"{role}: ancestor not a directory"
                )
        current = candidate
    return current


def _validate_existing_input_under_run_root(
    value: Any, run_root: Path, ext: str | None, role: str,
) -> Path:
    """Validate an existing current-owner non-symlink regular file
    strictly under ``run_root``. Walks every component below run_root
    and strict-resolves the leaf to its identity (no symlink escape)."""
    raw = _validate_abs_path(value, role)
    try:
        rel = raw.relative_to(run_root)
    except ValueError as exc:
        raise MergedExpectationGateError(
            f"{role}: not contained in run_root"
        ) from exc
    if str(rel) == ".":
        raise MergedExpectationGateError(f"{role}: equals run_root")
    if ext is not None and not str(rel).endswith(ext):
        raise MergedExpectationGateError(
            f"{role}: must end with {ext!r}"
        )
    leaf = _walk_no_symlink_chain(rel.parts, run_root, role)
    try:
        if leaf.is_symlink():
            raise MergedExpectationGateError(f"{role}: refusing symlink")
        st = leaf.lstat()
    except FileNotFoundError as exc:
        raise MergedExpectationGateError(f"{role}: not found") from exc
    except OSError as exc:
        raise MergedExpectationGateError(
            f"{role}: cannot lstat: {type(exc).__name__}"
        ) from exc
    if not stat.S_ISREG(st.st_mode):
        raise MergedExpectationGateError(f"{role}: not a regular file")
    _check_current_owner(st, role)
    try:
        resolved = leaf.resolve(strict=True)
    except FileNotFoundError as exc:
        raise MergedExpectationGateError(f"{role}: resolve failed") from exc
    except OSError as exc:
        raise MergedExpectationGateError(
            f"{role}: resolve failed: {type(exc).__name__}"
        ) from exc
    if resolved != leaf:
        raise MergedExpectationGateError(f"{role}: path escape after resolve")
    return leaf


def _validate_optional_input_under_run_root(
    value: Any, run_root: Path, ext: str | None, role: str,
) -> Path:
    """Like :func:`_validate_existing_input_under_run_root` but the leaf
    is permitted to be ABSENT (the pass-through case for
    ``shared_components.local.json``). When absent, returns the leaf
    path (the gate later treats absence as the null-digest case)."""
    raw = _validate_abs_path(value, role)
    try:
        rel = raw.relative_to(run_root)
    except ValueError as exc:
        raise MergedExpectationGateError(
            f"{role}: not contained in run_root"
        ) from exc
    if str(rel) == ".":
        raise MergedExpectationGateError(f"{role}: equals run_root")
    if ext is not None and not str(rel).endswith(ext):
        raise MergedExpectationGateError(
            f"{role}: must end with {ext!r}"
        )
    leaf = _walk_no_symlink_chain(rel.parts, run_root, role)
    try:
        if leaf.is_symlink():
            raise MergedExpectationGateError(f"{role}: refusing symlink")
        st = leaf.lstat()
    except FileNotFoundError:
        return leaf  # absent: pass-through case
    except OSError as exc:
        raise MergedExpectationGateError(
            f"{role}: cannot lstat: {type(exc).__name__}"
        ) from exc
    if not stat.S_ISREG(st.st_mode):
        raise MergedExpectationGateError(f"{role}: not a regular file")
    _check_current_owner(st, role)
    try:
        resolved = leaf.resolve(strict=True)
    except FileNotFoundError as exc:
        raise MergedExpectationGateError(f"{role}: resolve failed") from exc
    except OSError as exc:
        raise MergedExpectationGateError(
            f"{role}: resolve failed: {type(exc).__name__}"
        ) from exc
    if resolved != leaf:
        raise MergedExpectationGateError(f"{role}: path escape after resolve")
    return leaf


def _validate_output_target_under_run_root(
    value: Any, run_root: Path, role: str,
) -> Path:
    """Validate a JSON output target strictly under ``run_root``: the
    leaf may be absent OR an existing non-symlink regular file owned by
    the current user. Directories, symlinks, and path escape are
    rejected. Returns the absolute leaf Path."""
    raw = _validate_abs_path(value, role)
    try:
        rel = raw.relative_to(run_root)
    except ValueError as exc:
        raise MergedExpectationGateError(
            f"{role}: not contained in run_root"
        ) from exc
    if str(rel) == ".":
        raise MergedExpectationGateError(f"{role}: equals run_root")
    leaf = _walk_no_symlink_chain(rel.parts, run_root, role)
    try:
        if leaf.is_symlink():
            raise MergedExpectationGateError(f"{role}: refusing symlink")
        st = leaf.lstat()
    except FileNotFoundError:
        return leaf  # absent: safe to create later
    except OSError as exc:
        raise MergedExpectationGateError(
            f"{role}: cannot lstat: {type(exc).__name__}"
        ) from exc
    if not stat.S_ISREG(st.st_mode):
        raise MergedExpectationGateError(
            f"{role}: existing target not a regular file"
        )
    _check_current_owner(st, role)
    try:
        resolved = leaf.resolve(strict=True)
    except FileNotFoundError as exc:
        raise MergedExpectationGateError(f"{role}: resolve failed") from exc
    except OSError as exc:
        raise MergedExpectationGateError(
            f"{role}: resolve failed: {type(exc).__name__}"
        ) from exc
    if resolved != leaf:
        raise MergedExpectationGateError(f"{role}: path escape after resolve")
    return leaf


def _read_bounded(path: Path, role: str) -> bytes:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise MergedExpectationGateError(
            f"{role}: cannot stat: {type(exc).__name__}"
        ) from exc
    if size > _MAX_FILE_BYTES:
        raise MergedExpectationGateError(
            f"{role}: exceeds {_MAX_FILE_BYTES} bytes"
        )
    try:
        with open(str(path), "rb") as f:
            return f.read()
    except OSError as exc:
        raise MergedExpectationGateError(
            f"{role}: cannot read: {type(exc).__name__}"
        ) from exc


# ---------------------------------------------------------------------------
# SharedCore loaders (fixed sibling paths, no sys.path mutation).
# ---------------------------------------------------------------------------

_PROJECTION_MODULE: Any = None
_PROVENANCE_MODULE: Any = None


def _load_module_by_path(path: Path, cache_name: str, role: str) -> Any:
    _check_regular_nonsymlink(path, role)
    spec = importlib.util.spec_from_file_location(cache_name, str(path))
    if spec is None or spec.loader is None:
        raise MergedExpectationGateError(f"cannot load {role} module spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[cache_name] = module
    spec.loader.exec_module(module)
    return module


def _load_projection_module() -> Any:
    global _PROJECTION_MODULE
    if _PROJECTION_MODULE is None:
        _PROJECTION_MODULE = _load_module_by_path(
            _PROJECTION_MODULE_PATH,
            "p25d_shared_core_projection",
            "shared_core projection module",
        )
    return _PROJECTION_MODULE


def _load_provenance_module() -> Any:
    global _PROVENANCE_MODULE
    if _PROVENANCE_MODULE is None:
        _PROVENANCE_MODULE = _load_module_by_path(
            _PROVENANCE_MODULE_PATH,
            "p25d_shared_core_provenance",
            "shared_core provenance module",
        )
    return _PROVENANCE_MODULE


# ---------------------------------------------------------------------------
# Atomic publish (mode-0600 temp, fsync file + dir, atomic replace).
# ---------------------------------------------------------------------------


def _atomic_publish_canonical(
    target: Path, data: bytes, role: str,
) -> None:
    """Publish ``data`` to ``target`` atomically using a current-owner
    mode-0600 temp in the same safe directory; fsync the temp file and
    its parent directory, then atomically replace the target. Safe
    reruns may replace a safe existing regular output.
    """
    parent = target.parent
    # Validate parent is a current-owner non-symlink real dir.
    try:
        if parent.is_symlink():
            raise MergedExpectationGateError(f"{role}: parent is symlink")
        parent_st = parent.lstat()
    except FileNotFoundError as exc:
        raise MergedExpectationGateError(f"{role}: parent not found") from exc
    except OSError as exc:
        raise MergedExpectationGateError(
            f"{role}: parent lstat failed: {type(exc).__name__}"
        ) from exc
    if not stat.S_ISDIR(parent_st.st_mode):
        raise MergedExpectationGateError(f"{role}: parent not a directory")
    _check_current_owner(parent_st, f"{role}: parent")
    # If target exists, require non-symlink regular current-owner file.
    try:
        target_is_symlink = target.is_symlink()
    except OSError as exc:
        raise MergedExpectationGateError(
            f"{role}: target lstat failed: {type(exc).__name__}"
        ) from exc
    if target_is_symlink:
        raise MergedExpectationGateError(f"{role}: refusing symlink target")
    # Create the temp file in the same directory (atomic rename).
    fd = -1
    tmp_path: Path | None = None
    try:
        try:
            fd, tmp_name = tempfile.mkstemp(
                prefix=".p25d_prov_",
                suffix=".tmp",
                dir=str(parent),
            )
        except OSError as exc:
            raise MergedExpectationGateError(
                f"{role}: mkstemp failed: {type(exc).__name__}"
            ) from exc
        tmp_path = Path(tmp_name)
        # Restrict temp to current-owner mode 0600.
        try:
            os.chmod(fd, 0o600)
        except OSError as exc:
            raise MergedExpectationGateError(
                f"{role}: chmod failed: {type(exc).__name__}"
            ) from exc
        # Write the data.
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            fd = -1  # closed by the context manager
        except OSError as exc:
            raise MergedExpectationGateError(
                f"{role}: write/fsync failed: {type(exc).__name__}"
            ) from exc
        # fsync the parent directory so the rename is durable.
        try:
            dir_fd = os.open(str(parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            # fsync of directories is not supported on all platforms;
            # tolerate failure (the file fsync already happened).
            pass
        # Atomic replace.
        try:
            os.replace(str(tmp_path), str(target))
        except OSError as exc:
            raise MergedExpectationGateError(
                f"{role}: atomic replace failed: {type(exc).__name__}"
            ) from exc
        tmp_path = None  # consumed by os.replace
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Arg parsing.
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str]) -> dict[str, str]:
    """Parse the EXACT CLI arguments: seven flags, each required once.
    Raises SystemExit on any usage error, including an unknown flag.
    """
    ap = argparse.ArgumentParser(
        prog="flutter_merged_expectation_provenance_gate_v1.py",
        description=(
            "P2.5d Flutter merged-expectation provenance gate: a "
            "platform-origin primitive that proves the page canvas "
            "projection reconstructs the consumed merged expectation "
            "and atomically publishes P2.5c provenance."
        ),
        add_help=True,
    )
    ap.add_argument("--run-root", dest="run_root", required=True)
    ap.add_argument("--page-canvas-expected", dest="page_canvas_expected", required=True)
    ap.add_argument("--page-canvas-projection", dest="page_canvas_projection", required=True)
    ap.add_argument("--shared-components-local", dest="shared_components_local", required=True)
    ap.add_argument("--scene", dest="scene", required=True)
    ap.add_argument("--merged-expected", dest="merged_expected", required=True)
    ap.add_argument("--provenance-out", dest="provenance_out", required=True)
    parsed = ap.parse_args(argv)
    return {
        "run_root": parsed.run_root,
        "page_canvas_expected": parsed.page_canvas_expected,
        "page_canvas_projection": parsed.page_canvas_projection,
        "shared_components_local": parsed.shared_components_local,
        "scene": parsed.scene,
        "merged_expected": parsed.merged_expected,
        "provenance_out": parsed.provenance_out,
    }


# ---------------------------------------------------------------------------
# Core run.
# ---------------------------------------------------------------------------


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _run(args: dict[str, str]) -> dict[str, Any]:
    """Run the gate end-to-end. Returns a sanitized summary dict."""
    # 1. Path validation: run_root first, then every absolute path.
    run_root = _validate_run_root(args["run_root"])

    page_canvas_expected_path = _validate_existing_input_under_run_root(
        args["page_canvas_expected"], run_root, ".expected.json",
        "page_canvas_expected",
    )
    page_canvas_projection_path = _validate_existing_input_under_run_root(
        args["page_canvas_projection"], run_root, ".json",
        "page_canvas_projection",
    )
    scene_path = _validate_existing_input_under_run_root(
        args["scene"], run_root, ".json", "scene",
    )
    shared_components_local_path = _validate_optional_input_under_run_root(
        args["shared_components_local"], run_root, ".json",
        "shared_components_local",
    )
    merged_path = _validate_existing_input_under_run_root(
        args["merged_expected"], run_root, ".json", "merged_expected",
    )
    provenance_path = _validate_output_target_under_run_root(
        args["provenance_out"], run_root, "provenance_out",
    )

    # 2. Capsule verification + manifest binding + producer SHA.
    _verify_capsule()
    manifest = _load_manifest()
    producer_sha = _manifest_merge_producer_sha(manifest)

    # 3. Bounded reads of every input/output file.
    raw_expected = _read_bounded(page_canvas_expected_path, "page_canvas_expected")
    raw_projection = _read_bounded(page_canvas_projection_path, "page_canvas_projection")
    raw_scene = _read_bounded(scene_path, "scene")
    raw_merged = _read_bounded(merged_path, "merged_expected")
    local_is_present = shared_components_local_path.exists()
    if local_is_present:
        raw_local = _read_bounded(shared_components_local_path, "shared_components_local")
    else:
        raw_local = None

    # 4. Strict JSON decode of every doc.
    expected_doc = _decode_json_strict(raw_expected, "page_canvas_expected")
    projection_doc = _decode_json_strict(raw_projection, "page_canvas_projection")
    scene_doc = _decode_json_strict(raw_scene, "scene")
    merged_doc = _decode_json_strict(raw_merged, "merged_expected")
    # scene_doc and expected_doc must be objects.
    if not isinstance(expected_doc, dict):
        raise MergedExpectationGateError(
            "page_canvas_expected: root must be a JSON object"
        )
    if not isinstance(scene_doc, dict):
        raise MergedExpectationGateError("scene: root must be a JSON object")
    if not isinstance(merged_doc, dict):
        raise MergedExpectationGateError("merged_expected: root must be a JSON object")
    if not isinstance(projection_doc, dict):
        raise MergedExpectationGateError(
            "page_canvas_projection: root must be a JSON object"
        )

    # 5. Load SharedCore modules.
    projection_module = _load_projection_module()
    provenance_module = _load_provenance_module()

    # 6. Projection canonicality: raw projection bytes must equal
    # build_projection_bytes(projection_doc).
    try:
        rebuilt_projection = projection_module.build_projection_bytes(projection_doc)
    except projection_module.ProjectionValidationError:
        raise MergedExpectationGateError(
            "page_canvas_projection: shared_core validation raised"
        )
    except MergedExpectationGateError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise MergedExpectationGateError(
            f"page_canvas_projection: shared_core raised {type(exc).__name__}"
        ) from exc
    if rebuilt_projection != raw_projection:
        raise MergedExpectationGateError(
            "page_canvas_projection: canonical bytes mismatch"
        )

    # 7. Legacy byte parity: build_legacy_bytes(projection_doc)[0]
    # must equal raw page_canvas_expected bytes.
    try:
        rebuilt_legacy_expected, _slots = projection_module.build_legacy_bytes(
            projection_doc
        )
    except projection_module.ProjectionValidationError:
        raise MergedExpectationGateError(
            "page_canvas_projection: legacy bytes rebuild raised"
        )
    except MergedExpectationGateError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise MergedExpectationGateError(
            f"page_canvas_projection: legacy bytes rebuild raised {type(exc).__name__}"
        ) from exc
    if rebuilt_legacy_expected != raw_expected:
        raise MergedExpectationGateError(
            "page_canvas_expected: legacy bytes diverge from projection"
        )

    # 8. Merged canonicality: raw merged bytes must equal
    # json.dumps(merged_doc, ensure_ascii=False, indent=2) + "\n".
    canonical_merged = (
        json.dumps(merged_doc, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    if canonical_merged != raw_merged:
        raise MergedExpectationGateError(
            "merged_expected: canonical bytes mismatch"
        )

    # 9. Topology check: merged top-level fields other than "nodes"
    # must equal page expected document; page node IDs form the exact
    # prefix of merged node IDs; every page node value is unchanged;
    # shared node IDs are only the suffix.
    expected_nodes_obj = expected_doc.get("nodes")
    merged_nodes_obj = merged_doc.get("nodes")
    if not isinstance(expected_nodes_obj, dict):
        raise MergedExpectationGateError(
            "page_canvas_expected: 'nodes' must be an object"
        )
    if not isinstance(merged_nodes_obj, dict):
        raise MergedExpectationGateError(
            "merged_expected: 'nodes' must be an object"
        )
    page_node_ids = list(expected_nodes_obj.keys())
    merged_node_ids = list(merged_nodes_obj.keys())
    # Page node IDs form the exact prefix of merged node IDs.
    if merged_node_ids[: len(page_node_ids)] != page_node_ids:
        raise MergedExpectationGateError(
            "merged_expected: page node ids do not form the exact prefix"
        )
    shared_node_ids = merged_node_ids[len(page_node_ids):]
    # Every page node value is unchanged.
    for nid in page_node_ids:
        if merged_nodes_obj.get(nid) != expected_nodes_obj.get(nid):
            raise MergedExpectationGateError(
                "merged_expected: page node value changed"
            )
    # Top-level non-nodes fields must equal the page expected document.
    for key, value in merged_doc.items():
        if key == "nodes":
            continue
        if expected_doc.get(key) != value:
            raise MergedExpectationGateError(
                "merged_expected: top-level field diverges from page expected"
            )
    # Conversely, every expected_doc non-nodes key must be present in
    # merged_doc with the same value (no missing field).
    for key in expected_doc:
        if key == "nodes":
            continue
        if key not in merged_doc:
            raise MergedExpectationGateError(
                "merged_expected: missing top-level field vs page expected"
            )

    # 10. Missing-local case: merged must equal page expected, and the
    # shared node IDs must be empty.
    if not local_is_present:
        if merged_doc != expected_doc:
            raise MergedExpectationGateError(
                "merged_expected: missing-local case requires merged == page expected"
            )
        if shared_node_ids:
            raise MergedExpectationGateError(
                "merged_expected: missing-local case requires empty shared ids"
            )

    # 11. Compute SHA-256 over actual raw bytes.
    projection_sha = _sha256_bytes(raw_projection)
    local_sha: str | None = (
        _sha256_bytes(raw_local) if raw_local is not None else None
    )
    scene_sha = _sha256_bytes(raw_scene)
    merged_sha = _sha256_bytes(raw_merged)

    # 12. Build + validate provenance document via SharedCore.
    try:
        prov_doc = provenance_module.build_provenance(
            producerKind=_KIND_PRODUCER,
            producerSha256=producer_sha,
            pageCanvasProjectionSha256=projection_sha,
            sharedComponentsLocalSha256=local_sha,
            sceneSha256=scene_sha,
            mergedExpectedSha256=merged_sha,
            pageCanvasNodeIds=list(page_node_ids),
            sharedComponentNodeIds=list(shared_node_ids),
            mergedNodeIds=list(merged_node_ids),
        )
    except provenance_module.MergedExpectationProvenanceError:
        raise MergedExpectationGateError(
            "provenance: build_provenance validation raised"
        )
    except MergedExpectationGateError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise MergedExpectationGateError(
            f"provenance: build_provenance raised {type(exc).__name__}"
        ) from exc

    try:
        provenance_module.validate_provenance(prov_doc)
    except provenance_module.MergedExpectationProvenanceError:
        raise MergedExpectationGateError(
            "provenance: validate_provenance raised"
        )
    except MergedExpectationGateError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise MergedExpectationGateError(
            f"provenance: validate_provenance raised {type(exc).__name__}"
        ) from exc

    try:
        canonical_prov_bytes = provenance_module.build_provenance_bytes(prov_doc)
    except provenance_module.MergedExpectationProvenanceError:
        raise MergedExpectationGateError(
            "provenance: build_provenance_bytes raised"
        )
    except MergedExpectationGateError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise MergedExpectationGateError(
            f"provenance: build_provenance_bytes raised {type(exc).__name__}"
        ) from exc

    # 13. Atomic publish.
    _atomic_publish_canonical(
        provenance_path, canonical_prov_bytes, "provenance_out",
    )

    # 14. Re-open + revalidate. Re-read the published artifact and
    # require exact byte equality with what was written, then strict-
    # decode + validate again, and require canonical byte equality
    # with the locally-built canonical bytes.
    # Re-stat the provenance file (it must exist now).
    try:
        if provenance_path.is_symlink():
            raise MergedExpectationGateError(
                "provenance_out: post-publish symlink detected"
            )
        prov_st = provenance_path.lstat()
    except FileNotFoundError as exc:
        raise MergedExpectationGateError(
            "provenance_out: post-publish not found"
        ) from exc
    except OSError as exc:
        raise MergedExpectationGateError(
            f"provenance_out: post-publish lstat failed: {type(exc).__name__}"
        ) from exc
    if not stat.S_ISREG(prov_st.st_mode):
        raise MergedExpectationGateError(
            "provenance_out: post-publish not a regular file"
        )
    _check_current_owner(prov_st, "provenance_out: post-publish")
    published_bytes = _read_bounded(provenance_path, "provenance_out: post-publish")
    if published_bytes != canonical_prov_bytes:
        raise MergedExpectationGateError(
            "provenance_out: post-publish bytes diverge from canonical"
        )
    republished_doc = _decode_json_strict(
        published_bytes, "provenance_out: post-publish"
    )
    try:
        provenance_module.validate_provenance(republished_doc)
    except provenance_module.MergedExpectationProvenanceError:
        raise MergedExpectationGateError(
            "provenance_out: post-publish validate raised"
        )
    except MergedExpectationGateError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise MergedExpectationGateError(
            f"provenance_out: post-publish validate raised {type(exc).__name__}"
        ) from exc
    try:
        republished_canonical = provenance_module.build_provenance_bytes(
            republished_doc
        )
    except provenance_module.MergedExpectationProvenanceError:
        raise MergedExpectationGateError(
            "provenance_out: post-publish canonical bytes raised"
        )
    except MergedExpectationGateError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise MergedExpectationGateError(
            f"provenance_out: post-publish canonical bytes raised {type(exc).__name__}"
        ) from exc
    if republished_canonical != canonical_prov_bytes:
        raise MergedExpectationGateError(
            "provenance_out: post-publish canonical re-encode diverges"
        )

    # 15. Sanitized summary (no paths / raw content).
    return {
        "ok": True,
        "kind": "icp.flutter.merged-expectation-provenance-gate.v1",
        "schemaVersion": 1,
        "producerSha256": producer_sha,
        "pageNodeCount": len(page_node_ids),
        "sharedNodeCount": len(shared_node_ids),
        "mergedNodeCount": len(merged_node_ids),
        "localPresent": local_is_present,
    }


# ---------------------------------------------------------------------------
# CLI / public main().
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Parses the seven required flags exactly once each, runs the gate,
    and prints a stable sanitized JSON summary to stdout on success.
    On any failure, prints the type name plus fixed role-safe text to
    stderr (no traceback, no raw input/path/file-content leak, no
    environment) and returns a non-zero exit code.
    """
    if argv is None:
        argv = sys.argv[1:]
    try:
        args = _parse_args(list(argv))
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2

    try:
        summary = _run(args)
    except MergedExpectationGateError as exc:
        sys.stderr.write(f"MergedExpectationGateError: {exc}\n")
        return 1
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(
            f"MergedExpectationGateError: unexpected {type(exc).__name__}\n"
        )
        return 1

    sys.stdout.write(json.dumps(summary, ensure_ascii=False, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
