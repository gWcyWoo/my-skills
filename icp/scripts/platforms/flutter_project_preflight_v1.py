#!/usr/bin/env python3
"""ICP P2d1 Flutter ``project_preflight`` platform operation (executable,
read-only).

This is the first executable platform operation for the otherwise
inactive ``flutter-standard`` adapter. It is a fail-closed, read-only
project preflight that proves the selected root is a usable Flutter
project and resolves the Flutter toolchain from the trusted process
environment. It does not activate the Flutter adapter and does not
implement the other eight operation builders; the P2c descriptor remains
``new-port-required`` for this port.

Public Python API:

* ``preflight(project_root: str | os.PathLike[str]) -> dict[str, Any]``
  — verify the installed P2a vendored capsule first (via the fixed ICP
  path), then prove the project root is a real, lexically normalized
  directory that owns ``pubspec.yaml``, ``lib/``, and a strict
  ``.dart_tool/package_config.json`` whose package list contains the
  pubspec's top-level ``name``, and finally resolve ``flutter`` from the
  trusted process PATH, execute ``[resolved, "--version", "--machine"]``
  in a fixed 30 second timeout, and return the canonical report of kind
  ``icp.project-preflight.v1``.

CLI:

* ``python3 flutter_project_preflight_v1.py --project-root ABSOLUTE_PATH``
  — emits exactly one canonical JSON object on stdout (exit 0) for
  success, or one canonical JSON object on stderr (exit 2) for failure.
  No traceback, no secret, no child stderr, no arbitrary exception text.

Locked boundaries:

* Read-only. The operation never writes to the project root, capsule,
  registry, run root, or ``iff/``. It never mutates any file.
* ``profile_id`` is fixed to ``flutter-standard``; no API or CLI
  override is exposed for executable, env, argv, command, interpreter,
  runner, registry, or activation.
* Production code derives the ICP root, capsule root, and verifier path
  only from this module's installed file location. No public override is
  exposed for skill root, capsule root, verifier path, executable,
  command, script, interpreter, environment, argv, or activation.
* The operation verifies the installed P2a vendored capsule first,
  before any project or toolchain inspection. No sibling ``iff/``
  dependency is allowed: this module never imports, reads, executes, or
  follows a symlink into ``iff/**``.
* Only the Python standard library is used.
* The operation resolves ``flutter`` only with ``shutil.which("flutter")``
  from the current trusted process environment, then
  ``Path.resolve(strict=True)``. A symlink returned by PATH is allowed
  only after canonicalization; the report records the final target.
* The subprocess invocation is exactly
  ``[resolved_flutter, "--version", "--machine"]`` with
  ``subprocess.run``, ``shell=False``, ``cwd=project_root``, captured
  stdout/stderr, text mode with a fixed UTF-8/strict decoder
  (independent of the process locale), a fixed 30 second timeout, and
  no user-controlled environment overlay.
* The CLI never exposes child stderr or arbitrary exception text. Stable
  diagnostic messages may identify the failed invariant and exception
  class only.

Local error code is ``project_preflight_failed``; it never extends
``icp_common.ALL_ERROR_CODES``.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Public schema constants.
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1
KIND = "icp.project-preflight.v1"
OPERATION_ID = "flutter.project_preflight.v1"
PLATFORM_ID = "flutter"
PROFILE_ID = "flutter-standard"
SCRIPT_NAME = "flutter_project_preflight_v1.py"

# Local error code. This is NOT an ICP pre-claim code and does not
# extend icp_common.ALL_ERROR_CODES.
CODE = "project_preflight_failed"

# ---------------------------------------------------------------------------
# Fixed file-system vocabulary inside the project root.
# ---------------------------------------------------------------------------

PUBSPEC_NAME = "pubspec.yaml"
LIB_NAME = "lib"
PACKAGE_CONFIG_REL = ".dart_tool/package_config.json"

# Path components below the root that this operation inspects. Each tuple
# is (relative parts, expected leaf kind) and is walked from the resolved
# project root with non-symlink enforcement on every component.
PUBSPEC_PARTS: tuple[str, ...] = (PUBSPEC_NAME,)
LIB_PARTS: tuple[str, ...] = (LIB_NAME,)
PACKAGE_CONFIG_PARTS: tuple[str, ...] = (".dart_tool", "package_config.json")

# Size ceilings (bytes). These are part of the operation's contract: an
# attacker-supplied pubspec or package_config that exceeds the ceiling is
# rejected before it is parsed.
PUBSPEC_MAX_BYTES = 2 * 1024 * 1024  # 2 MiB
PACKAGE_CONFIG_MAX_BYTES = 8 * 1024 * 1024  # 8 MiB
VERSION_PAYLOAD_MAX_BYTES = 1024 * 1024  # 1 MiB

# Subprocess behaviour: argv, timeout, shell, mode. These are part of the
# settled contract and never accept a caller override.
FLUTTER_VERSION_ARGV: tuple[str, ...] = ("--version", "--machine")
FLUTTER_VERSION_TIMEOUT_SECONDS = 30

# ---------------------------------------------------------------------------
# Fixed production paths derived from this module's installed location.
# Accepts NO override; this is the runtime surface.
# ---------------------------------------------------------------------------

ICP_ROOT = Path(__file__).resolve().parents[2]
VERIFY_TOOL = ICP_ROOT / "scripts" / "verify_vendor_iff_v1.py"


class PreflightError(ValueError):
    """A local project_preflight failure.

    Raised for any capsule verification error, project-root validation
    error, project artifact error, package-config shape error, pubspec
    name parse error, toolchain resolution error, subprocess invocation
    error, or CLI usage error. The CLI catches this and emits one
    canonical JSON error object.
    """


# ---------------------------------------------------------------------------
# Small deterministic helpers (canonical JSON, digests, strict decode).
# ---------------------------------------------------------------------------


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    for key, _value in pairs:
        if key in seen:
            raise PreflightError(f"duplicate JSON key: {key!r}")
        seen.add(key)
    return dict(pairs)


def _decode_json_strict(raw: bytes, role: str) -> Any:
    """Decode UTF-8 strict JSON with duplicate-key rejection.

    Returns the parsed object (any type). Callers validate the shape.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PreflightError(f"{role}: not UTF-8: {type(exc).__name__}") from exc
    try:
        return json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except PreflightError:
        raise
    except json.JSONDecodeError as exc:
        raise PreflightError(f"{role}: not valid JSON") from exc


def _is_sha256_hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value.islower()
        and all(c in "0123456789abcdef" for c in value)
    )


# ---------------------------------------------------------------------------
# File / directory type-safe checks (refuse symlinks and non-regular
# nodes everywhere the operation walks below the root).
# ---------------------------------------------------------------------------


def _check_nonsymlink_dir(path: Path, role: str) -> None:
    """Refuse symlinks and non-directories for ``path``."""
    try:
        if path.is_symlink():
            raise PreflightError(f"{role}: refusing symlink: {path}")
        st = path.lstat()
    except OSError as exc:
        raise PreflightError(f"{role}: cannot lstat {path}: {type(exc).__name__}") from exc
    if not stat.S_ISDIR(st.st_mode):
        raise PreflightError(f"{role}: not a directory: {path}")


def _check_nonsymlink_regular_file(path: Path, role: str) -> None:
    """Refuse symlinks and non-regular files for ``path``."""
    try:
        if path.is_symlink():
            raise PreflightError(f"{role}: refusing symlink: {path}")
        st = path.lstat()
    except OSError as exc:
        raise PreflightError(f"{role}: cannot lstat {path}: {type(exc).__name__}") from exc
    if not stat.S_ISREG(st.st_mode):
        raise PreflightError(f"{role}: not a regular file: {path}")


def _check_child_under_root(
    root: Path, rel_parts: tuple[str, ...], role: str, expect: str
) -> Path:
    """Walk ``root / rel_parts`` and verify no symlinked ancestor, no
    symlinked leaf, the expected leaf kind, and post-resolution
    containment within ``root``.

    ``root`` itself is assumed already canonical (supplied path equals
    strict resolve). Every component below is inspected for symlinks and
    non-matching file type. The resolved path must equal the supplied
    path and remain inside ``root``.
    """
    if not rel_parts:
        raise PreflightError(f"{role}: empty relative path")
    current = root
    last = len(rel_parts) - 1
    for index, part in enumerate(rel_parts):
        if not part or part in {".", ".."}:
            raise PreflightError(f"{role}: unsafe path component {part!r}")
        if "\\" in part or "/" in part or "\x00" in part:
            raise PreflightError(f"{role}: unsafe path component {part!r}")
        current = current / part
        if index < last:
            _check_nonsymlink_dir(current, f"{role}: ancestor {part}")
        else:
            if expect == "file":
                _check_nonsymlink_regular_file(current, role)
            elif expect == "dir":
                _check_nonsymlink_dir(current, role)
            else:
                raise PreflightError(f"{role}: unknown expect kind {expect!r}")
    # Strict-resolve the leaf and verify it did not move. Because every
    # component is non-symlink and the root is canonical, the resolved
    # path equals the supplied path; any divergence is an escape attempt.
    try:
        resolved = current.resolve(strict=True)
    except FileNotFoundError as exc:
        raise PreflightError(f"{role}: missing after walk: {current}") from exc
    except OSError as exc:
        raise PreflightError(f"{role}: resolve failed: {type(exc).__name__}") from exc
    if resolved != current:
        raise PreflightError(
            f"{role}: path escape after resolve: {current} -> {resolved}"
        )
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PreflightError(f"{role}: not contained in project root") from exc
    return current


# ---------------------------------------------------------------------------
# Project-root validation: absolute / lexically normalized / real dir /
# resolve(strict=True) match (rejects symlinked root or ancestor).
# ---------------------------------------------------------------------------


def _validate_project_root(project_root: str | os.PathLike[str]) -> Path:
    if isinstance(project_root, (bytes, bytearray)):
        raise PreflightError("project_root: must be str or os.PathLike, got bytes")
    if not isinstance(project_root, (str, os.PathLike)):
        raise PreflightError(
            f"project_root: must be str or os.PathLike, got {type(project_root).__name__}"
        )
    # Coerce PathLike to str via fspath; reject bytes / non-str paths.
    try:
        root_str = os.fspath(project_root)
    except TypeError as exc:
        raise PreflightError(
            f"project_root: cannot coerce to path: {type(project_root).__name__}"
        ) from exc
    if not isinstance(root_str, str):
        raise PreflightError("project_root: must be a text path, got bytes")
    raw_path = Path(root_str)
    if not raw_path.is_absolute():
        raise PreflightError(f"project_root: not absolute: {root_str!r}")
    # Reject any '..' component outright.
    if any(part == ".." for part in raw_path.parts):
        raise PreflightError(f"project_root: contains '..': {root_str!r}")
    # Lexical normalization: normpath(supplied) must equal supplied.
    normalized = os.path.normpath(root_str)
    if normalized != root_str:
        raise PreflightError(
            f"project_root: not lexically normalized: {root_str!r}"
        )
    # Strict-resolve; a symlinked root or any symlinked ancestor diverges
    # from the supplied path and is rejected rather than silently
    # changing ownership.
    try:
        resolved = raw_path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise PreflightError(f"project_root: does not exist: {raw_path}") from exc
    except RuntimeError as exc:
        raise PreflightError(
            f"project_root: resolve loop: {type(exc).__name__}"
        ) from exc
    except OSError as exc:
        raise PreflightError(
            f"project_root: resolve failed: {type(exc).__name__}"
        ) from exc
    if resolved != raw_path:
        raise PreflightError(
            f"project_root: supplied path differs from strict resolve "
            f"(symlinked root or ancestor): {raw_path} -> {resolved}"
        )
    # Must be a real directory (non-symlink, since resolve matched).
    _check_nonsymlink_dir(resolved, "project_root")
    return resolved


# ---------------------------------------------------------------------------
# Capsule verification (delegated to the P2a runtime gate).
# ---------------------------------------------------------------------------


_VERIFY_MODULE: Any = None


def _load_verify_module():
    """Load ``verify_vendor_iff_v1`` by file path (no sys.path mutation)."""
    global _VERIFY_MODULE
    if _VERIFY_MODULE is None:
        _check_nonsymlink_regular_file(VERIFY_TOOL, "verify_vendor_iff_v1.py")
        spec = importlib.util.spec_from_file_location(
            "verify_vendor_iff_v1_p2d1", str(VERIFY_TOOL)
        )
        if spec is None or spec.loader is None:
            raise PreflightError("cannot load verify_vendor_iff_v1 module spec")
        module = importlib.util.module_from_spec(spec)
        sys.modules["verify_vendor_iff_v1_p2d1"] = module
        spec.loader.exec_module(module)
        _VERIFY_MODULE = module
    return _VERIFY_MODULE


def _verify_capsule() -> dict[str, Any]:
    """Verify the installed vendored capsule via the P2a runtime gate.

    Returns the canonical capsule-success payload. Any integrity
    violation surfaces as a :class:`PreflightError`. Never imports,
    reads, executes, or follows a symlink into ``iff/**``.

    Module loading and ``verify_skill()`` are split into two explicit
    guarded stages so a same-name exception class raised before the
    fixed verifier module loaded can never be mis-trusted as a known
    capsule-integrity error:

    * Stage 1 — ``_load_verify_module()``: a :class:`PreflightError`
      is preserved; any other exception surfaces as
      ``capsule verification raised <ExceptionClass>`` (type only).
      No ``str(exc)`` is emitted at this stage, because the fixed
      verifier has not yet loaded and any exception class — even one
      named ``CapsuleIntegrityError`` — is untrusted.
    * Stage 2 — ``verify_skill()`` on the successfully loaded module:
      only here may an exception be classified with
      ``isinstance(exc, verifier_module.CapsuleIntegrityError)`` and
      converted to the known ``capsule verification failed: <message>``
      diagnostic. Any other exception surfaces as type only.
    """
    # Stage 1: load the fixed verifier module by file path. Any
    # exception here is untrusted — class-name heuristics are
    # explicitly forbidden because an attacker-controlled exception
    # could be named ``CapsuleIntegrityError``.
    try:
        verifier_module = _load_verify_module()
    except PreflightError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise PreflightError(
            f"capsule verification raised {type(exc).__name__}"
        ) from exc

    # Stage 2: the fixed verifier module loaded successfully. Only now
    # is its ``CapsuleIntegrityError`` class trustworthy for
    # isinstance-based classification.
    try:
        return verifier_module.verify_skill(ICP_ROOT)
    except verifier_module.CapsuleIntegrityError as exc:
        raise PreflightError(f"capsule verification failed: {exc}") from exc
    except PreflightError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise PreflightError(
            f"capsule verification raised {type(exc).__name__}"
        ) from exc


# ---------------------------------------------------------------------------
# Pubspec top-level ``name`` parser (deterministic, no YAML dependency).
#
# The pubspec is YAML, but we deliberately parse only the restricted
# top-level ``name:`` scalar we need for the package-config cross-check.
# The accepted shape is exactly:
#
#   name: <plain-scalar>
#
# where <plain-scalar> is a single line whose value:
#   - may be a bare unquoted token with no leading whitespace, no '#',
#     no quotes, no ':' (no flow/quoted indirection),
#   - may be wrapped in ASCII single quotes 'foo' or double quotes
#     "foo" (double quotes allow the JSON-style escape set \", \\, \/,
#     \b, \f, \n, \r, \t, \uXXXX; single quotes are literal except ''),
#   - may be followed by an inline `` # comment`` that is stripped
#     before value validation,
#   - must be non-empty after unquoting / escape resolution.
#
# Ambiguous forms are rejected up front: a top-level ``name:`` key that
# appears more than once, an indented ``name:`` line (which is a child
# of another mapping), a value that is empty after stripping, a quoted
# scalar with an invalid escape, or any non-scalar form.
# ---------------------------------------------------------------------------


_DQUOTE_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}


def _unescape_double_quoted(literal: str) -> str:
    """Resolve a double-quoted YAML scalar body. Rejects unknown escapes."""
    out: list[str] = []
    i = 0
    n = len(literal)
    while i < n:
        ch = literal[i]
        if ch == "\\":
            i += 1
            if i >= n:
                raise PreflightError("pubspec name: trailing backslash in double-quote")
            esc = literal[i]
            if esc == "u":
                hexrun = literal[i + 1 : i + 5]
                if len(hexrun) != 4 or any(
                    c not in "0123456789abcdefABCDEF" for c in hexrun
                ):
                    raise PreflightError(
                        "pubspec name: invalid \\u escape in double-quote"
                    )
                out.append(chr(int(hexrun, 16)))
                i += 5
                continue
            if esc == "x":
                hexrun = literal[i + 1 : i + 3]
                if len(hexrun) != 2 or any(
                    c not in "0123456789abcdefABCDEF" for c in hexrun
                ):
                    raise PreflightError(
                        "pubspec name: invalid \\x escape in double-quote"
                    )
                out.append(chr(int(hexrun, 16)))
                i += 3
                continue
            if esc in _DQUOTE_ESCAPES:
                out.append(_DQUOTE_ESCAPES[esc])
                i += 1
                continue
            raise PreflightError(
                f"pubspec name: invalid double-quote escape \\{esc}"
            )
        out.append(ch)
        i += 1
    return "".join(out)


def _parse_scalar_value(value: str) -> str:
    """Resolve a single-line YAML scalar value (already comment-stripped)
    to a Python str. Rejects empty and ambiguous forms.

    The leading whitespace after ``name:`` is the YAML key/value
    separator, not part of the value; it is stripped before parsing.
    Trailing whitespace is stripped for both plain and quoted scalars
    (single-line form)."""
    # Strip the YAML separator (leading whitespace) and trailing
    # whitespace for single-line scalars.
    value = value.lstrip(" \t")
    value = value.rstrip()
    if not value:
        raise PreflightError("pubspec name: empty value")
    if value[0] == '"':
        if len(value) < 2 or value[-1] != '"' or len(value) == 1:
            raise PreflightError("pubspec name: unterminated double-quote")
        body = value[1:-1]
        return _unescape_double_quoted(body)
    if value[0] == "'":
        if len(value) < 2 or value[-1] != "'" or len(value) == 1:
            raise PreflightError("pubspec name: unterminated single-quote")
        body = value[1:-1]
        # YAML single-quote escaping: '' is the only escape (literal ').
        return body.replace("''", "'")
    # Plain scalar: no quotes, no leading sigil. Reject anything that
    # contains a bare ':' followed by space (mapping indicator) or starts
    # with a YAML reserved sigil.
    if value[0] in "&*!|>%@`":
        raise PreflightError("pubspec name: plain scalar has reserved sigil")
    if ": " in value or value.endswith(":"):
        raise PreflightError("pubspec name: plain scalar looks like a mapping")
    if "#" in value:
        # An inline comment should have been stripped already; any '#'
        # remaining in a plain scalar is treated as ambiguous.
        raise PreflightError("pubspec name: unstripped inline comment")
    return value


def _strip_inline_comment(value: str) -> str:
    """Strip a YAML inline ``# comment`` from a scalar value, respecting
    single/double quoting. Returns the value before the comment."""
    i = 0
    n = len(value)
    quote: str | None = None
    while i < n:
        ch = value[i]
        if quote is None:
            if ch == "#":
                # A '#' starting a comment must be preceded by whitespace
                # or start of value; either way, this is the comment.
                # YAML requires a space or start before '#'.
                if i == 0 or value[i - 1] in (" ", "\t"):
                    return value[:i]
                # An inline '#' inside a plain scalar that is not preceded
                # by whitespace is part of the scalar; do not strip.
                i += 1
                continue
            if ch in ('"', "'"):
                quote = ch
            i += 1
            continue
        # Inside a quoted region.
        if ch == "\\" and quote == '"':
            i += 2
            continue
        if ch == quote:
            if quote == "'" and i + 1 < n and value[i + 1] == "'":
                i += 2
                continue
            quote = None
        i += 1
    return value


def _parse_pubspec_name(raw: bytes) -> str:
    """Parse the top-level ``name:`` scalar from pubspec bytes.

    Returns the exact name string. Raises :class:`PreflightError` on any
    ambiguous, duplicated, missing, empty, malformed, or invalid-escape
    value.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PreflightError(f"pubspec.yaml: not UTF-8: {type(exc).__name__}") from exc
    name: str | None = None
    name_line: int | None = None
    for line_no, line in enumerate(text.splitlines(), start=1):
        # Strip a trailing newline-equivalent (already split). Skip blank
        # lines and full-line comments.
        if not line.strip():
            continue
        stripped_left = line.lstrip()
        if stripped_left.startswith("#"):
            continue
        # Detect document markers (we don't accept multi-document pubspecs
        # for the restricted scalar).
        if stripped_left == "---" or stripped_left == "..." or stripped_left.startswith(
            "%YAML"
        ) or stripped_left.startswith("%TAG"):
            raise PreflightError("pubspec.yaml: document markers not supported")
        indented = line[0] in (" ", "\t")
        if not stripped_left.startswith("name:") and not (
            stripped_left.startswith("name ") and not indented
        ):
            continue
        if indented:
            # An indented ``name:`` is a child mapping key, not the
            # top-level package name. Ignore it for safety.
            continue
        # Must be exactly "name:" or "name " followed by ':'.
        if not stripped_left.startswith("name:"):
            # e.g. "name something: value" — not the package name key.
            continue
        if name is not None:
            raise PreflightError(
                f"pubspec.yaml: duplicate top-level name at line {line_no} "
                f"(first at line {name_line})"
            )
        rest = stripped_left[len("name:"):]
        rest = _strip_inline_comment(rest)
        resolved = _parse_scalar_value(rest)
        if not resolved:
            raise PreflightError("pubspec.yaml: empty name value")
        name = resolved
        name_line = line_no
    if name is None:
        raise PreflightError("pubspec.yaml: missing top-level name")
    return name


# ---------------------------------------------------------------------------
# Project inspection: pubspec, lib, package_config.
# ---------------------------------------------------------------------------


def _inspect_project(root: Path) -> dict[str, Any]:
    """Inspect the project root and return the canonical ``project``
    block plus the resolved pubspec ``name`` (used by the package-config
    cross-check; not part of the report)."""
    pubspec_path = _check_child_under_root(
        root, PUBSPEC_PARTS, "pubspec.yaml", expect="file"
    )
    lib_path = _check_child_under_root(
        root, LIB_PARTS, "lib directory", expect="dir"
    )
    package_config_path = _check_child_under_root(
        root, PACKAGE_CONFIG_PARTS, ".dart_tool/package_config.json", expect="file"
    )

    # Size ceilings before parse.
    pubspec_bytes = _read_bounded(pubspec_path, PUBSPEC_MAX_BYTES, "pubspec.yaml")
    package_config_bytes = _read_bounded(
        package_config_path, PACKAGE_CONFIG_MAX_BYTES, ".dart_tool/package_config.json"
    )

    name = _parse_pubspec_name(pubspec_bytes)

    # Package config strict JSON: object, configVersion==2, packages list,
    # at least one package whose name equals the pubspec name.
    cfg = _decode_json_strict(package_config_bytes, ".dart_tool/package_config.json")
    if not isinstance(cfg, dict):
        raise PreflightError(
            ".dart_tool/package_config.json: root must be a JSON object"
        )
    if cfg.get("configVersion") != 2:
        raise PreflightError(
            f".dart_tool/package_config.json: configVersion must be 2, "
            f"got {cfg.get('configVersion')!r}"
        )
    packages = cfg.get("packages")
    if not isinstance(packages, list):
        raise PreflightError(
            ".dart_tool/package_config.json: packages must be a list"
        )
    matched = False
    for index, entry in enumerate(packages):
        if not isinstance(entry, dict):
            raise PreflightError(
                f".dart_tool/package_config.json: packages[{index}] not an object"
            )
        entry_name = entry.get("name")
        if not isinstance(entry_name, str) or not entry_name:
            # Skip non-name entries silently; many real package configs
            # include generated metadata entries without a name.
            continue
        if entry_name == name:
            matched = True
            break
    if not matched:
        raise PreflightError(
            f".dart_tool/package_config.json: no package named {name!r} "
            f"(from pubspec.yaml) appears in packages list"
        )

    return {
        "report_block": {
            "lib_directory": LIB_NAME,
            "package_config": PACKAGE_CONFIG_REL,
            "pubspec": PUBSPEC_NAME,
            "pubspec_sha256": _sha256_bytes(pubspec_bytes),
        },
        "pubspec_name": name,
    }


def _read_bounded(path: Path, max_bytes: int, role: str) -> bytes:
    """Read up to ``max_bytes + 1`` bytes; reject if the file exceeds the
    ceiling. Returns the bytes (no more than ``max_bytes``)."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise PreflightError(f"{role}: cannot stat: {type(exc).__name__}") from exc
    if size > max_bytes:
        raise PreflightError(
            f"{role}: size {size} exceeds ceiling {max_bytes}"
        )
    try:
        return path.read_bytes()
    except OSError as exc:
        raise PreflightError(f"{role}: cannot read: {type(exc).__name__}") from exc


# ---------------------------------------------------------------------------
# Trusted toolchain resolution.
# ---------------------------------------------------------------------------


def _resolve_flutter() -> Path:
    """Resolve the Flutter executable from the trusted process PATH.

    Calls ``shutil.which("flutter")`` against the inherited environment,
    then ``Path.resolve(strict=True)`` and requires the final target to
    be a regular executable file. A symlink returned by PATH is allowed
    only after canonicalization; the returned path is the final target.
    """
    found = shutil.which("flutter")
    if not found:
        raise PreflightError("flutter executable not found in PATH")
    try:
        resolved = Path(found).resolve(strict=True)
    except FileNotFoundError as exc:
        raise PreflightError(
            "flutter executable: PATH entry does not exist after resolve"
        ) from exc
    except RuntimeError as exc:
        raise PreflightError(
            f"flutter executable: resolve loop: {type(exc).__name__}"
        ) from exc
    except OSError as exc:
        raise PreflightError(
            f"flutter executable: resolve failed: {type(exc).__name__}"
        ) from exc
    try:
        st = resolved.stat()
    except OSError as exc:
        raise PreflightError(
            f"flutter executable: stat failed: {type(exc).__name__}"
        ) from exc
    if not stat.S_ISREG(st.st_mode):
        raise PreflightError(
            f"flutter executable: resolved target is not a regular file: {resolved}"
        )
    if not os.access(resolved, os.X_OK):
        raise PreflightError(
            f"flutter executable: resolved target is not executable: {resolved}"
        )
    return resolved


def _run_flutter_version(resolved_flutter: Path, project_root: Path) -> bytes:
    """Execute ``[resolved_flutter, --version, --machine]`` with no env
    overlay, ``shell=False``, ``cwd=project_root``, captured
    stdout/stderr, text mode with a fixed UTF-8/strict decoder
    (independent of the process locale), and the fixed 30 second
    timeout.

    Returns the UTF-8-encoded stdout bytes used for parsing. Raises
    :class:`PreflightError` on any failure: nonzero exit, non-empty
    stderr, timeout, OSError, Unicode decode/encode failure, oversized
    stdout, or any unexpected exception. **Never** echoes child stderr,
    raw child bytes, or arbitrary exception text in error messages.
    """
    argv = [str(resolved_flutter), *FLUTTER_VERSION_ARGV]
    try:
        result = subprocess.run(
            argv,
            shell=False,
            cwd=str(project_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=FLUTTER_VERSION_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise PreflightError(
            f"flutter --version: timed out after "
            f"{FLUTTER_VERSION_TIMEOUT_SECONDS}s"
        ) from exc
    except OSError as exc:
        raise PreflightError(
            f"flutter --version: OSError: {type(exc).__name__}"
        ) from exc
    except UnicodeError as exc:
        # A strict UTF-8 decode failure on child stdout/stderr. Never
        # echo the raw child bytes or arbitrary exception text; surface
        # the invariant and exception class only.
        raise PreflightError(
            f"flutter --version: stdout not UTF-8: {type(exc).__name__}"
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise PreflightError(
            f"flutter --version: raised {type(exc).__name__}"
        ) from exc
    if result.returncode != 0:
        raise PreflightError(
            f"flutter --version: exited {result.returncode}"
        )
    # Reject non-empty stderr. The stderr bytes are never echoed back.
    if result.stderr:
        raise PreflightError("flutter --version: produced non-empty stderr")
    raw_text = result.stdout or ""
    try:
        raw_bytes = raw_text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise PreflightError(
            "flutter --version: stdout not UTF-8 encodable"
        ) from exc
    if len(raw_bytes) > VERSION_PAYLOAD_MAX_BYTES:
        raise PreflightError(
            f"flutter --version: stdout exceeds {VERSION_PAYLOAD_MAX_BYTES} bytes"
        )
    return raw_bytes


def _parse_version_payload(raw_bytes: bytes) -> tuple[str, str]:
    """Parse the Flutter ``--version --machine`` JSON payload.

    Returns ``(framework_version, dart_sdk_version)``. Requires a root
    object, exact machine keys ``frameworkVersion`` and
    ``dartSdkVersion`` (both non-empty strings), and duplicate-key
    rejection.
    """
    obj = _decode_json_strict(raw_bytes, "flutter --version payload")
    if not isinstance(obj, dict):
        raise PreflightError(
            "flutter --version payload: root must be a JSON object"
        )
    framework = obj.get("frameworkVersion")
    dart = obj.get("dartSdkVersion")
    if not isinstance(framework, str) or not framework:
        raise PreflightError(
            "flutter --version payload: frameworkVersion must be a non-empty string"
        )
    if not isinstance(dart, str) or not dart:
        raise PreflightError(
            "flutter --version payload: dartSdkVersion must be a non-empty string"
        )
    return framework, dart


def _inspect_toolchain(project_root: Path) -> dict[str, Any]:
    """Resolve flutter, execute ``--version --machine``, parse, and
    return the canonical ``toolchain`` block."""
    resolved = _resolve_flutter()
    try:
        flutter_bytes = resolved.read_bytes()
    except OSError as exc:
        raise PreflightError(
            f"flutter executable: cannot read for digest: {type(exc).__name__}"
        ) from exc
    raw_version_bytes = _run_flutter_version(resolved, project_root)
    framework, dart = _parse_version_payload(raw_version_bytes)
    return {
        "flutter_executable": str(resolved),
        "flutter_executable_sha256": _sha256_bytes(flutter_bytes),
        "flutter_version": framework,
        "dart_sdk_version": dart,
        "version_payload_sha256": _sha256_bytes(raw_version_bytes),
    }


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------


def preflight(project_root: str | os.PathLike[str]) -> dict[str, Any]:
    """Verify the installed capsule, validate the project root, inspect
    the project artifacts, resolve and probe the Flutter toolchain from
    the trusted process PATH, and return the canonical
    ``icp.project-preflight.v1`` report.

    The operation is read-only and writes nothing. ``profile_id`` is
    fixed to ``flutter-standard``; no executable, env, argv, command,
    interpreter, runner, registry, or activation override is accepted.
    """
    # Capsule verification happens first, before any project or
    # toolchain inspection.
    _verify_capsule()
    root = _validate_project_root(project_root)
    project = _inspect_project(root)
    toolchain = _inspect_toolchain(root)
    return {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "operation_id": OPERATION_ID,
        "platform_id": PLATFORM_ID,
        "profile_id": PROFILE_ID,
        "project_root": str(root),
        "project": project["report_block"],
        "toolchain": toolchain,
    }


def inspect_entry_requirements(project_root: str | os.PathLike[str]) -> dict[str, Any]:
    missing: list[dict[str, str]] = []
    try:
        root = _validate_project_root(project_root)
    except Exception:
        root = None
        missing.append(
            {
                "id": "project_root",
                "owner": "user",
                "remediation": "supply a canonical Flutter project directory",
                "detail": "project root is missing, invalid, or symlinked",
            }
        )
    report = None
    config = None
    if root is not None:
        project_files = ("pubspec.yaml", "lib")
        absent_project = [name for name in project_files if not (root / name).exists()]
        if absent_project:
            missing.append(
                {
                    "id": "project_materials",
                    "owner": "user",
                    "remediation": "supply the complete Flutter project",
                    "detail": "missing: " + ", ".join(absent_project),
                }
            )
        dependency_files = ("pubspec.lock", ".dart_tool/package_config.json")
        absent_dependencies = [name for name in dependency_files if not (root / name).is_file()]
        if absent_dependencies:
            missing.append(
                {
                    "id": "dependencies",
                    "owner": "environment",
                    "remediation": "run flutter pub get in project_root",
                    "detail": "missing: " + ", ".join(absent_dependencies),
                }
            )
        if shutil.which("flutter") is None:
            missing.append(
                {
                    "id": "toolchain",
                    "owner": "environment",
                    "remediation": "install Flutter and expose it on PATH",
                    "detail": "missing tool: flutter",
                }
            )
        config_path = root / ".icp" / "platform-config.json"
        try:
            if config_path.is_symlink() or not config_path.is_file():
                raise ValueError("missing")
            config = _decode_json_strict(config_path.read_bytes(), "platform config")
            if not isinstance(config, dict) or tuple(config) != ("device_id",):
                raise ValueError("shape")
            device_id = config["device_id"]
            if not isinstance(device_id, str) or not device_id or "\n" in device_id or "\r" in device_id:
                raise ValueError("device")
        except Exception:
            config = None
            missing.append(
                {
                    "id": "runtime_config",
                    "owner": "user",
                    "remediation": "create .icp/platform-config.json with device_id",
                    "detail": "Flutter runtime config is missing or invalid",
                }
            )
        try:
            report = preflight(root)
        except Exception:
            report = None
            known_ids = {item["id"] for item in missing}
            if not known_ids.intersection({"project_materials", "toolchain", "dependencies"}):
                missing.append(
                    {
                        "id": "project_materials",
                        "owner": "user",
                        "remediation": "repair the selected Flutter project",
                        "detail": "Flutter project or capsule validation failed",
                    }
                )
        if config is not None and report is not None:
            result = subprocess.run(
                [report["toolchain"]["flutter_executable"], "devices", "--machine"],
                cwd=root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
            )
            try:
                devices = json.loads(result.stdout.decode("utf-8")) if result.returncode == 0 else []
            except Exception:
                devices = []
            if not isinstance(devices, list) or not any(
                isinstance(device, dict) and device.get("id") == config["device_id"]
                for device in devices
            ):
                missing.append(
                    {
                        "id": "runtime_target",
                        "owner": "environment",
                        "remediation": "start or connect the selected Flutter device",
                        "detail": "selected Flutter device is unavailable",
                    }
                )
            else:
                report = dict(report)
                report["runtime_target"] = {
                    "kind": "icp.flutter-runtime-target.v1",
                    "device_id": config["device_id"],
                    "platform_config_digest": hashlib.sha256(
                        _canonical_json_bytes(config)
                    ).hexdigest(),
                    "status": "pass",
                }
        elif config is not None:
            missing.append(
                {
                    "id": "runtime_target",
                    "owner": "environment",
                    "remediation": "resolve Flutter project/toolchain checks, then verify device availability",
                    "detail": "device availability check is deferred by another Flutter prerequisite",
                }
            )
    return {
        "kind": "icp.flutter-entry-requirements-inspection.v1",
        "schema_version": 1,
        "platform_id": PLATFORM_ID,
        "profile_id": PROFILE_ID,
        "platform_report": report if not missing else None,
        "missing_inputs": sorted(missing, key=lambda item: item["id"]),
    }


# ---------------------------------------------------------------------------
# CLI (one canonical JSON object; no traceback; no override flags).
# ---------------------------------------------------------------------------


class _JSONArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that raises PreflightError instead of exiting."""

    def error(self, message: str) -> None:  # type: ignore[override]
        raise PreflightError(f"cli: {message}")


def _emit(stream, payload: dict[str, Any]) -> None:
    stream.write(_canonical_json_bytes(payload).decode("utf-8"))
    stream.flush()


def _build_parser() -> _JSONArgumentParser:
    parser = _JSONArgumentParser(
        prog=SCRIPT_NAME,
        description=(
            "ICP P2d1 Flutter project_preflight operation (read-only, "
            "fail-closed)."
        ),
        add_help=True,
    )
    parser.add_argument(
        "--project-root",
        dest="project_root",
        required=True,
        help="Absolute path to the Flutter project root to preflight.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    raw = sys.argv[1:] if argv is None else list(argv)
    try:
        parser = _build_parser()
        args = parser.parse_args(raw)
        report = preflight(args.project_root)
        _emit(sys.stdout, report)
        return 0
    except PreflightError as exc:
        _emit(
            sys.stderr,
            {"ok": False, "code": CODE, "message": str(exc)},
        )
        return 2
    except Exception as exc:  # noqa: BLE001
        _emit(
            sys.stderr,
            {
                "ok": False,
                "code": CODE,
                "message": type(exc).__name__,
            },
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
