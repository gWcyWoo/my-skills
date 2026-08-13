#!/usr/bin/env python3
"""ICP P2b lanhu-figma DesignSource wrapper.

This module is a self-contained DesignSource adapter over the immutable,
integrity-gated iFF v1 capsule under ``icp/vendor/iff_v1/scripts/``. It
exposes four settled DesignSource operations and a CLI surface, without any
dependency on sibling ``iff/``:

* ``resolve(locator) -> board_ref`` — strict parse of an HTTP(S) Lanhu
  locator with exactly one non-empty ``image_id`` query value; emits a
  deterministic board ref derived from the locator bytes.
* ``probe(locator) -> design_source_probe.v1`` — verifies the installed
  capsule first, then runs only the fixed ``fetch.py`` and
  ``download_cover.py`` capsule primitives using temporary storage; never
  mutates the task CSV, project root, or final bundle root; removes every
  temporary artifact on success and failure.
* ``fetch_normalize(locator, bundle_root) -> design_bundle_report.v1`` —
  verifies the capsule, runs the fixed seven-step capsule sequence in a
  sibling staging directory, finalizes canonical
  ``design_provenance.json`` / ``reference_manifest.json``, fully validates
  the staged bundle, and publishes with one atomic rename when the final
  bundle path is absent.
* ``verify_bundle(bundle_root) -> design_bundle_report.v1`` — fails closed
  on missing/extra/symlinked/non-regular entries, duplicate JSON keys,
  digest mismatch, malformed PNG, missing ``figma_json.artboard``, a scene
  whose ``sourceSchema`` is not ``lanhu_figma_json``, provenance/board-ref
  mismatch, or asset-inventory mismatch.

Locked boundaries:

* Production code derives its ICP root, capsule root, and script paths only
  from this file's installed location. No public override is exposed for
  skill root, capsule root, script path, command, interpreter, runner,
  environment, or registry.
* The wrapper never accepts, places in argv, persists, inspects, logs,
  copies, or serializes any cookie/token/secret. The subprocess environment
  is inherited as-is because the legacy capsule scripts own their existing
  credential lookup; nothing in this module reads or modifies it.
* Only the Python standard library is used. Persistent artifacts and CLI
  output are canonical UTF-8 JSON (sorted keys, two-space indent, newline).
* No shell execution, no arbitrary argv pass-through. The subprocess
  ``argv`` is always the fixed per-step contract.

CLI output is exactly one canonical JSON object on stdout for success
(exit 0) or one canonical JSON object on stderr for failure (exit 2). No
traceback. Local error codes are scoped to this DesignSource and never
extend ``icp_common.ALL_ERROR_CODES``.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import importlib.util
import json
import math
import os
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import urllib.parse
import zlib
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Public schema constants.
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1
KIND_PROBE = "design_source_probe.v1"
KIND_REPORT = "design_bundle_report.v1"
KIND_PROVENANCE = "icp.lanhu-figma.design-provenance.v1"
KIND_REFERENCE_MANIFEST = "icp.lanhu-figma.reference-manifest.v1"
SOURCE_ID = "lanhu-figma"
IR_SCHEMA = "lanhu_figma_json"
SCRIPT_NAME = "lanhu_figma_v1.py"

# Local error code. This is NOT an ICP pre-claim code and does not extend
# icp_common.ALL_ERROR_CODES.
CODE_DESIGN = "design_source_failed"

# Required top-level artifacts (other than provenance itself). The exact
# set a published bundle must contain at the top level.
REQUIRED_TOPLEVEL_ARTIFACTS = (
    "raw.json",
    "spec.md",
    "reference.png",
    "reference_manifest.json",
    "scene.json",
    "tokens.json",
    "assets_manifest.json",
    "design_classification.json",
)
JSON_TOPLEVEL_ARTIFACTS = frozenset(
    {
        "raw.json",
        "reference_manifest.json",
        "scene.json",
        "tokens.json",
        "assets_manifest.json",
        "design_classification.json",
    }
)
PROVENANCE_NAME = "design_provenance.json"
REFERENCE_MANIFEST_NAME = "reference_manifest.json"
ASSETS_DIR_NAME = "assets"
LEGACY_ASSETS_MANIFEST_NAME = "manifest.json"

# Fixed seven-step capsule sequence (script name, argv builder). The argv
# is the exact fixed contract for each primitive; no override is exposed.
# Defined here as data so it is auditable and cannot drift into arbitrary
# argv pass-through.

# ---------------------------------------------------------------------------
# Fixed production paths derived from this module's installed location.
# Accepts NO override; this is the runtime surface.
# ---------------------------------------------------------------------------

ICP_ROOT = Path(__file__).resolve().parents[2]
CAPSULE_SCRIPTS = ICP_ROOT / "vendor" / "iff_v1" / "scripts"
VERIFY_TOOL = ICP_ROOT / "scripts" / "verify_vendor_iff_v1.py"


class LanhuFigmaError(ValueError):
    """A local DesignSource failure.

    Raised for any locator parse error, capsule verification error, step
    failure, atomic-publication violation, or bundle verification failure.
    The CLI catches this and emits one canonical JSON error object.
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
            raise LanhuFigmaError(f"duplicate JSON key: {key!r}")
        seen.add(key)
    return dict(pairs)


def _decode_json_strict(raw: bytes, role: str) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LanhuFigmaError(f"{role}: not UTF-8: {exc}") from exc
    try:
        obj = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise LanhuFigmaError(f"{role}: not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise LanhuFigmaError(
            f"{role}: root must be a JSON object, got {type(obj).__name__}"
        )
    return obj


def _decode_json_strict_any(raw: bytes, role: str) -> Any:
    """Strict UTF-8 JSON decode that accepts any root type (object/array/etc).

    Used for the legacy ``assets/manifest.json``, which the upstream
    ``fetch.py`` always writes as a JSON array of slice records.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LanhuFigmaError(f"{role}: not UTF-8: {exc}") from exc
    try:
        return json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise LanhuFigmaError(f"{role}: not valid JSON: {exc}") from exc


def _check_regular_file(path: Path, role: str) -> None:
    """Refuse symlinks / non-regular / unreadable files."""
    try:
        if path.is_symlink():
            raise LanhuFigmaError(f"{role}: refusing symlink: {path}")
        st = path.lstat()
    except OSError as exc:
        raise LanhuFigmaError(f"{role}: cannot lstat {path}: {exc}") from exc
    if not stat.S_ISREG(st.st_mode):
        raise LanhuFigmaError(f"{role}: not a regular file: {path}")
    if not os.access(path, os.R_OK):
        raise LanhuFigmaError(f"{role}: unreadable file: {path}")


def _check_regular_dir(path: Path, role: str) -> None:
    """Refuse symlinks / non-directories."""
    try:
        if path.is_symlink():
            raise LanhuFigmaError(f"{role}: refusing symlink dir: {path}")
        st = path.lstat()
    except OSError as exc:
        raise LanhuFigmaError(f"{role}: cannot lstat dir {path}: {exc}") from exc
    if not stat.S_ISDIR(st.st_mode):
        raise LanhuFigmaError(f"{role}: not a directory: {path}")


def _check_path_chain_no_symlink(path: Path, role: str) -> None:
    """Reject if any existing component of the absolute form of ``path`` is
    a symlink. Does NOT call ``.resolve()`` on the whole path; the
    caller-supplied path identity is preserved and inspected component-by-
    component. On macOS, ``os.path.abspath`` does not resolve symlinks; it
    only normalizes ``.`` and ``..``, so caller-supplied symlinks are
    preserved and detected.
    """
    abs_path = Path(os.path.abspath(str(path)))
    root = abs_path.anchor or "/"
    current = Path(root)
    for part in abs_path.parts[1:]:
        current = current / part
        if os.path.islink(str(current)):
            raise LanhuFigmaError(
                f"{role}: refusing symlink in path chain: {current}"
            )


def _fsync_dir(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _png_validate_and_size(data: bytes) -> tuple[int, int]:
    """Deterministic structural PNG parser.

    Validates:
    * 8-byte PNG signature.
    * First chunk is IHDR with length exactly 13.
    * Positive width/height and valid fixed PNG method fields.
    * Chunk boundaries and CRCs throughout.
    * At least one IDAT chunk.
    * Terminal empty IEND with no trailing bytes.

    Returns ``(width, height)`` on success. Raises
    :class:`LanhuFigmaError` on any structural violation. Standard-library
    ``struct`` + ``zlib`` only.
    """
    if len(data) < 8 or data[:8] != _PNG_SIGNATURE:
        raise LanhuFigmaError("not a PNG file: bad signature")
    offset = 8
    seen_ihdr = False
    seen_idat = False
    width = 0
    height = 0
    while offset < len(data):
        if offset + 8 > len(data):
            raise LanhuFigmaError(
                f"malformed PNG: truncated chunk header at offset {offset}"
            )
        chunk_len = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_data_start = offset + 8
        chunk_data_end = chunk_data_start + chunk_len
        if chunk_data_end + 4 > len(data):
            raise LanhuFigmaError(
                f"malformed PNG: truncated chunk {chunk_type!r} data+CRC"
            )
        chunk_data = data[chunk_data_start:chunk_data_end]
        stored_crc = struct.unpack(
            ">I", data[chunk_data_end : chunk_data_end + 4]
        )[0]
        computed_crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
        if stored_crc != computed_crc:
            raise LanhuFigmaError(
                f"malformed PNG: CRC mismatch in chunk {chunk_type!r}"
            )
        if not seen_ihdr:
            if chunk_type != b"IHDR":
                raise LanhuFigmaError(
                    f"malformed PNG: first chunk must be IHDR, got {chunk_type!r}"
                )
            if chunk_len != 13:
                raise LanhuFigmaError(
                    f"malformed PNG: IHDR length must be 13, got {chunk_len}"
                )
            width, height, bit_depth, color_type, comp, filt, interlace = (
                struct.unpack(">IIBBBBB", chunk_data)
            )
            if width <= 0 or height <= 0:
                raise LanhuFigmaError(
                    f"malformed PNG: non-positive dimensions {width}x{height}"
                )
            if bit_depth not in (1, 2, 4, 8, 16):
                raise LanhuFigmaError(
                    f"malformed PNG: invalid bit depth {bit_depth}"
                )
            if comp != 0 or filt != 0:
                raise LanhuFigmaError("malformed PNG: invalid compression/filter")
            if interlace not in (0, 1):
                raise LanhuFigmaError(
                    f"malformed PNG: invalid interlace method {interlace}"
                )
            seen_ihdr = True
        elif chunk_type == b"IHDR":
            raise LanhuFigmaError("malformed PNG: duplicate IHDR")
        elif chunk_type == b"IDAT":
            seen_idat = True
        elif chunk_type == b"IEND":
            if chunk_len != 0:
                raise LanhuFigmaError("malformed PNG: IEND must be empty")
            if offset + 12 != len(data):
                raise LanhuFigmaError("malformed PNG: trailing bytes after IEND")
            if not seen_idat:
                raise LanhuFigmaError("malformed PNG: IEND before any IDAT")
            return int(width), int(height)
        offset = chunk_data_end + 4
    raise LanhuFigmaError("malformed PNG: no IEND chunk")


def _png_size(path: Path) -> tuple[int, int]:
    """Validate and return ``(width, height)`` of a PNG file at ``path``."""
    _check_regular_file(path, "reference.png")
    return _png_validate_and_size(path.read_bytes())


# ---------------------------------------------------------------------------
# Raw artboard bbox extraction + reference tolerance check.
#
# Matches the frozen legacy key semantics from vendored
# common.py:45-93 (bbox_of) and check_design_artifacts.py:42-43,53-60,126-134.
# ---------------------------------------------------------------------------


def _num(value: Any) -> float | None:
    """Coerce a value to float, rejecting bools and non-finite values."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _num_from_keys(obj: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key in obj:
            v = _num(obj[key])
            if v is not None:
                return v
    return None


def _bbox_of(node: Any) -> list[float] | None:
    """Extract a 4-element [x, y, w, h] bbox from a Figma node.

    Matches vendored common.py:67-93 exactly:
    1. Direct ``bbox`` list of 4 nums.
    2. First matching dict among ``absoluteBoundingBox``, ``absoluteRenderBounds``,
       ``bounds``, ``frame``, ``rect`` — extracting x/left/l, y/top/t,
       width/w, height/h.
    3. Direct x/left, y/top, width/w, height/h on the node.
    Returns ``None`` if no bbox can be extracted.
    """
    if not isinstance(node, dict):
        return None
    direct = node.get("bbox")
    if isinstance(direct, list) and len(direct) == 4:
        nums = [_num(v) for v in direct]
        if all(v is not None for v in nums):
            return [float(v) for v in nums]
    for key in (
        "absoluteBoundingBox",
        "absoluteRenderBounds",
        "bounds",
        "frame",
        "rect",
    ):
        box = node.get(key)
        if isinstance(box, dict):
            x = _num_from_keys(box, "x", "left", "l")
            y = _num_from_keys(box, "y", "top", "t")
            w = _num_from_keys(box, "width", "w")
            h = _num_from_keys(box, "height", "h")
            if None not in (x, y, w, h):
                return [float(x), float(y), float(w), float(h)]
    x = _num_from_keys(node, "x", "left")
    y = _num_from_keys(node, "y", "top")
    w = _num_from_keys(node, "width", "w")
    h = _num_from_keys(node, "height", "h")
    if None not in (x, y, w, h):
        return [float(x), float(y), float(w), float(h)]
    return None


def _raw_artboard_bbox(raw_obj: dict[str, Any]) -> list[float] | None:
    """Extract the artboard bbox from a raw.json object.

    Matches vendored check_design_artifacts.py:53-60 exactly.
    """
    figma = raw_obj.get("figma_json") if isinstance(raw_obj, dict) else None
    if not isinstance(figma, dict):
        return None
    artboard = figma.get("artboard")
    if not isinstance(artboard, dict):
        return None
    return _bbox_of(artboard)


def _close(a: float, b: float, tolerance: float = 1.0) -> bool:
    """Match vendored check_design_artifacts.py:42-43 exactly."""
    return abs(float(a) - float(b)) <= tolerance


def _check_reference_matches_artboard(
    ref_w: int,
    ref_h: int,
    raw_obj: dict[str, Any],
) -> None:
    """Verify reference PNG dimensions match the raw artboard bbox within 1.0.

    Matches vendored check_design_artifacts.py:126-134. Missing bbox fails.
    Raises :class:`LanhuFigmaError` on mismatch.
    """
    bbox = _raw_artboard_bbox(raw_obj)
    if bbox is None:
        raise LanhuFigmaError(
            "raw.json missing figma_json.artboard bbox"
        )
    raw_w, raw_h = bbox[2], bbox[3]
    if not _close(raw_w, ref_w) or not _close(raw_h, ref_h):
        raise LanhuFigmaError(
            f"reference.png size does not match raw artboard: "
            f"reference={ref_w}x{ref_h} raw={raw_w}x{raw_h}"
        )


# ---------------------------------------------------------------------------
# Capsule verification (delegated to the P2a runtime gate).
# ---------------------------------------------------------------------------


_VERIFY_MODULE: Any = None


def _load_verify_module():
    """Load ``verify_vendor_iff_v1`` by file path (no sys.path mutation)."""
    global _VERIFY_MODULE
    if _VERIFY_MODULE is None:
        _check_regular_file(VERIFY_TOOL, "verify_vendor_iff_v1.py")
        spec = importlib.util.spec_from_file_location(
            "verify_vendor_iff_v1", str(VERIFY_TOOL)
        )
        if spec is None or spec.loader is None:
            raise LanhuFigmaError("cannot load verify_vendor_iff_v1 module spec")
        module = importlib.util.module_from_spec(spec)
        sys.modules["verify_vendor_iff_v1"] = module
        spec.loader.exec_module(module)
        _VERIFY_MODULE = module
    return _VERIFY_MODULE


def _verify_capsule() -> dict[str, Any]:
    """Verify the installed vendored capsule via the P2a runtime gate.

    Returns the canonical capsule-success payload. Any integrity violation
    surfaces as a :class:`LanhuFigmaError`. Never imports, reads, executes,
    or follows a symlink into ``iff/**``.
    """
    module = _load_verify_module()
    try:
        return module.verify_skill(ICP_ROOT)
    except module.CapsuleIntegrityError as exc:
        raise LanhuFigmaError(f"capsule verification failed: {exc}") from exc
    except Exception as exc:
        raise LanhuFigmaError(
            f"capsule verification raised {type(exc).__name__}"
        ) from exc


# ---------------------------------------------------------------------------
# Locator resolution.
# ---------------------------------------------------------------------------


# Sensitive query keys that must never appear in a locator. Normalized
# case-insensitively; hyphen/underscore equivalence is applied before
# comparison so ``Api-Key`` and ``api_key`` are both rejected.
_SENSITIVE_QUERY_KEYS = frozenset(
    {
        "token",
        "access_token",
        "api_key",
        "apikey",
        "password",
        "passwd",
        "secret",
        "cookie",
        "authorization",
        "auth",
        "bearer",
    }
)


def _normalize_query_key(key: str) -> str:
    """Normalize a query key for case-insensitive, hyphen/underscore-
    equivalent comparison."""
    return key.lower().replace("-", "_")


def _parse_locator(locator: Any) -> dict[str, Any]:
    """Strict parse of a Lanhu HTTP(S) locator.

    Accepts only:
    * a non-empty string,
    * an ``http`` or ``https`` scheme,
    * a non-empty network location,
    * no URL fragment,
    * no userinfo (credentials),
    * exactly one non-blank ``image_id`` query value.

    Returns a small parsed dict. Raises :class:`LanhuFigmaError` otherwise.
    """
    if not isinstance(locator, str):
        raise LanhuFigmaError("locator must be a string")
    if not locator:
        raise LanhuFigmaError("locator must be non-empty")
    if "\x00" in locator:
        raise LanhuFigmaError("locator contains NUL")
    if locator.strip() != locator or "\n" in locator or "\r" in locator:
        raise LanhuFigmaError("locator has leading/trailing whitespace or newlines")
    try:
        parsed = urllib.parse.urlsplit(locator)
    except ValueError as exc:
        raise LanhuFigmaError(f"locator is malformed: {exc}") from exc
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise LanhuFigmaError(
            f"locator scheme must be http or https: {scheme!r}"
        )
    if not parsed.netloc:
        raise LanhuFigmaError("locator missing network location")
    if parsed.fragment:
        raise LanhuFigmaError("locator must not contain a fragment")
    if parsed.username or parsed.password:
        raise LanhuFigmaError("locator must not contain credentials")
    try:
        qsl = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    except ValueError as exc:
        raise LanhuFigmaError(f"locator query is malformed: {exc}") from exc
    image_ids = [value for (key, value) in qsl if key == "image_id"]
    if len(image_ids) != 1:
        raise LanhuFigmaError(
            f"locator must have exactly one image_id query value; got {len(image_ids)}"
        )
    image_id = image_ids[0]
    if not image_id or not image_id.strip():
        raise LanhuFigmaError("locator image_id must be non-empty")
    # Reject any sensitive query key (case-insensitive, hyphen/underscore
    # equivalent). The locator must not carry credentials in the query.
    for key, _value in qsl:
        if _normalize_query_key(key) in _SENSITIVE_QUERY_KEYS:
            raise LanhuFigmaError(
                "locator must not contain sensitive query keys"
            )
    return {
        "scheme": scheme,
        "netloc": parsed.netloc,
        "path": parsed.path,
        "query": parsed.query,
        "image_id": image_id,
    }


def _board_ref(locator: str) -> str:
    """Deterministic board ref derived from the locator bytes.

    Form: ``lanhu-figma:v1:<sha256-hex>``. Stable across processes and
    hosts; preserves the locator as data via the provenance file.
    """
    digest = hashlib.sha256(locator.encode("utf-8")).hexdigest()
    return f"{SOURCE_ID}:v1:{digest}"


def resolve(locator: str) -> str:
    """Resolve a Lanhu HTTP(S) locator to a deterministic board ref.

    Raises :class:`LanhuFigmaError` for any non-conforming locator.
    """
    _parse_locator(locator)
    return _board_ref(locator)


# ---------------------------------------------------------------------------
# Private subprocess step runner.
#
# This single module-level function is the seam used by tests to monkeypatch
# capsule primitives with deterministic synthesizers. The production
# implementation NEVER accepts a credential, env override, or arbitrary
# argv: it always invokes ``[sys.executable, <fixed capsule script>,
# <fixed per-step argv>]`` with the inherited environment, because the
# legacy capsule scripts own their own credential lookup. The wrapper never
# inspects, logs, copies, or serializes the environment.
# ---------------------------------------------------------------------------


def _run_step(script_name: str, argv: list[str]) -> None:
    """Invoke a fixed capsule primitive. No shell, no arbitrary argv.

    Raises :class:`LanhuFigmaError` if the script is missing, the
    subprocess invocation fails, the script exits non-zero, OR the
    invocation raises any other unexpected exception. **Never** includes
    child stdout/stderr content or arbitrary exception text in the error
    message; only the fixed script name and stable exit status are
    reported so a secret-bearing stderr cannot leak through this wrapper.
    """
    script_path = CAPSULE_SCRIPTS / script_name
    try:
        _check_regular_file(script_path, f"capsule script {script_name}")
    except LanhuFigmaError:
        raise
    cmd = [sys.executable, str(script_path), *argv]
    try:
        result = subprocess.run(
            cmd,
            env=os.environ,  # inherited; never inspected/logged by this wrapper
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        # Report only the stable exception class + errno, never arbitrary
        # exception text which may carry credential fragments.
        err_name = getattr(exc, "errno", None)
        if err_name is not None:
            raise LanhuFigmaError(
                f"{script_name}: OSError errno={err_name}"
            ) from exc
        raise LanhuFigmaError(
            f"{script_name}: OSError"
        ) from exc
    except Exception as exc:  # noqa: BLE001
        # Report only the stable exception class name, never the message.
        raise LanhuFigmaError(
            f"{script_name}: {type(exc).__name__}"
        ) from exc
    if result.returncode != 0:
        # Report only the fixed script name and exit status. NEVER include
        # child stdout/stderr — it may carry credential fragments.
        raise LanhuFigmaError(
            f"{script_name} exited {result.returncode}"
        )


# ---------------------------------------------------------------------------
# Asset inventory + reference manifest builders.
# ---------------------------------------------------------------------------


def _inventory_assets(assets_dir: Path) -> list[list[str]]:
    """Sorted relative-path / SHA-256 inventory of every regular file under
    ``assets_dir``. Refuses symlinks and non-regular files.
    """
    out: list[list[str]] = []
    if not assets_dir.exists():
        return out
    _check_regular_dir(assets_dir, "assets dir")
    for p in sorted(assets_dir.rglob("*")):
        if p.is_dir():
            continue
        rel = p.relative_to(assets_dir).as_posix()
        _check_regular_file(p, f"assets file {rel}")
        out.append([rel, _sha256_file(p)])
    return out


def _write_reference_manifest(stage: Path) -> dict[str, Any]:
    """Build and write ``reference_manifest.json`` in ``stage``."""
    ref_path = stage / "reference.png"
    _check_regular_file(ref_path, "reference.png")
    width, height = _png_size(ref_path)
    payload = {
        "kind": KIND_REFERENCE_MANIFEST,
        "schema_version": SCHEMA_VERSION,
        "reference": "reference.png",
        "sha256": _sha256_file(ref_path),
        "width": width,
        "height": height,
    }
    (stage / REFERENCE_MANIFEST_NAME).write_bytes(_canonical_json_bytes(payload))
    return payload


def _write_provenance(
    stage: Path,
    *,
    board_ref: str,
    locator: str,
) -> dict[str, Any]:
    """Build and write ``design_provenance.json`` in ``stage``."""
    artifacts: dict[str, str] = {}
    for name in REQUIRED_TOPLEVEL_ARTIFACTS:
        artifacts[name] = _sha256_file(stage / name)
    assets_inventory = _inventory_assets(stage / ASSETS_DIR_NAME)
    payload = {
        "kind": KIND_PROVENANCE,
        "schema_version": SCHEMA_VERSION,
        "source_id": SOURCE_ID,
        "board_ref": board_ref,
        "locator": locator,
        "ir_schema": IR_SCHEMA,
        "artifacts": artifacts,
        "assets_inventory": assets_inventory,
    }
    (stage / PROVENANCE_NAME).write_bytes(_canonical_json_bytes(payload))
    return payload


# ---------------------------------------------------------------------------
# Race-free non-clobber publication via native same-filesystem no-replace
# primitive. Implemented using Python standard-library ``ctypes`` over:
#
#   Darwin: renamex_np(src, dst, RENAME_EXCL=0x00000004)
#   Linux:  renameat2(AT_FDCWD, src, AT_FDCWD, dst, RENAME_NOREPLACE=1)
#
# There is NO check-then-rename, NO ``os.rename``, and NO ``os.replace``
# fallback. The native exclusive rename is the decisive publication gate.
# On unsupported platforms or a libc without the required primitive, fail
# closed.
# ---------------------------------------------------------------------------

# Platform-specific constants.
_DARWIN_RENAME_EXCL = 0x00000004
_LINUX_AT_FDCWD = -100
_LINUX_RENAME_NOREPLACE = 1


def _load_native_no_replace():
    """Resolve the native no-replace rename function for the current
    platform, or raise :class:`LanhuFigmaError` if unavailable.

    Returns a callable ``(src: Path, dst: Path) -> None`` that atomically
    renames ``src`` to ``dst`` only if ``dst`` does not exist.
    """
    platform = sys.platform
    try:
        libc = ctypes.CDLL(None, use_errno=True)
    except OSError as exc:
        raise LanhuFigmaError(
            f"cannot load libc for atomic publication: OSError"
        ) from exc

    if platform == "darwin":
        try:
            func = libc.renamex_np
        except AttributeError as exc:
            raise LanhuFigmaError(
                "renamex_np not available; cannot publish atomically"
            ) from exc
        func.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
        func.restype = ctypes.c_int

        def _publish(src: Path, dst: Path) -> None:
            ret = func(
                os.fsencode(str(src)),
                os.fsencode(str(dst)),
                _DARWIN_RENAME_EXCL,
            )
            if ret != 0:
                err = ctypes.get_errno()
                _raise_publish_errno(err, dst)

        return _publish

    if platform.startswith("linux"):
        try:
            func = libc.renameat2
        except AttributeError as exc:
            raise LanhuFigmaError(
                "renameat2 not exported by libc; cannot publish atomically"
            ) from exc
        func.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        func.restype = ctypes.c_int

        def _publish(src: Path, dst: Path) -> None:
            ret = func(
                _LINUX_AT_FDCWD,
                os.fsencode(str(src)),
                _LINUX_AT_FDCWD,
                os.fsencode(str(dst)),
                _LINUX_RENAME_NOREPLACE,
            )
            if ret != 0:
                err = ctypes.get_errno()
                _raise_publish_errno(err, dst)

        return _publish

    raise LanhuFigmaError(
        f"platform {platform!r} has no atomic no-replace publication primitive"
    )


def _raise_publish_errno(err: int, dst: Path) -> None:
    """Translate an errno from the native no-replace rename to a
    :class:`LanhuFigmaError`. EEXIST/ENOTEMPTY are the expected
    ``destination exists`` cases; other errno values are surfaced without
    traceback through the CLI boundary.
    """
    if err in (errno.EEXIST, errno.ENOTEMPTY):
        raise LanhuFigmaError(
            f"bundle_root exists; refusing overwrite: {dst}"
        )
    name = errno.errorcode.get(err)
    if name:
        raise LanhuFigmaError(
            f"atomic publication failed: errno={err} ({name})"
        )
    raise LanhuFigmaError(f"atomic publication failed: errno={err}")


def _atomic_publish_no_replace(src: Path, dst: Path) -> None:
    """Atomically rename ``src`` to ``dst`` only if ``dst`` does not exist.

    Uses the native same-filesystem no-replace primitive. There is no
    check-then-rename, ``os.rename``, or ``os.replace`` fallback. The
    native exclusive rename is the decisive gate.
    """
    _publish = _load_native_no_replace()
    _publish(src, dst)


def _run_seven_steps(locator: str, stage: Path) -> None:
    """Run the exact fixed capsule sequence into ``stage``.

    Each tuple is (script name, fixed argv list). The argv is constructed
    only from the resolved ``locator`` and the staging path; there is no
    arbitrary pass-through and no credential is ever placed in argv.
    """
    raw_path = stage / "raw.json"
    spec_path = stage / "spec.md"
    reference_path = stage / "reference.png"
    assets_dir = stage / ASSETS_DIR_NAME
    assets_manifest_legacy = assets_dir / LEGACY_ASSETS_MANIFEST_NAME
    scene_path = stage / "scene.json"
    tokens_path = stage / "tokens.json"
    assets_manifest_path = stage / "assets_manifest.json"
    design_classification_path = stage / "design_classification.json"

    # fetch.py owns target_dir = dirname(--output); ensure assets dir exists
    # so the wrapper can later normalize the legacy manifest in place.
    assets_dir.mkdir(parents=True, exist_ok=True)

    steps: list[tuple[str, list[str]]] = [
        (
            "fetch.py",
            ["--url", locator, "--output", str(raw_path)],
        ),
        (
            "write.py",
            ["--input", str(raw_path), "--output", str(spec_path)],
        ),
        (
            "download_cover.py",
            ["--url", locator, "--out", str(reference_path)],
        ),
        (
            "export_figma_scene.py",
            [
                "--raw", str(raw_path),
                "--assets", str(assets_manifest_legacy),
                "--out", str(scene_path),
            ],
        ),
        (
            "export_tokens.py",
            ["--scene", str(scene_path), "--out", str(tokens_path)],
        ),
        (
            "export_assets_manifest.py",
            ["--scene", str(scene_path), "--out", str(assets_manifest_path)],
        ),
        (
            "classify_design.py",
            [
                "--raw", str(raw_path),
                "--reference", str(reference_path),
                "--out", str(design_classification_path),
            ],
        ),
    ]
    for script_name, argv in steps:
        _run_step(script_name, argv)

    # The legacy ``assets/manifest.json`` must always exist in a published
    # bundle. fetch.py only writes it when slices exist; normalize an absent
    # manifest to an empty JSON array so the bundle layout is stable.
    if not assets_manifest_legacy.exists():
        assets_manifest_legacy.write_bytes(b"[]\n")
    else:
        # Validate legacy manifest is at least strict JSON (it is a list of
        # slice records, not a JSON object).
        _decode_json_strict_any(
            assets_manifest_legacy.read_bytes(), "assets/manifest.json"
        )


def _finalize_bundle(
    stage: Path,
    *,
    locator: str,
    board_ref: str,
) -> dict[str, Any]:
    """Build ``reference_manifest.json`` + ``design_provenance.json`` in
    ``stage`` and return the canonical report payload derived from the
    staged bundle (also validating it fully).

    Validates that the reference PNG dimensions match the raw artboard
    bbox within the 1.0 tolerance before finalizing.
    """
    ref_path = stage / "reference.png"
    ref_w, ref_h = _png_size(ref_path)
    raw_obj = _decode_json_strict(
        (stage / "raw.json").read_bytes(), "raw.json"
    )
    _check_reference_matches_artboard(ref_w, ref_h, raw_obj)
    _write_reference_manifest(stage)
    _write_provenance(stage, board_ref=board_ref, locator=locator)
    return _build_report_from_bundle(stage, board_ref=board_ref, locator=locator)


def fetch_normalize(locator: str, bundle_root: Path) -> dict[str, Any]:
    """Run the fixed capsule sequence and publish a canonical bundle.

    Verifies the installed capsule first, runs the seven fixed capsule
    primitives into a sibling staging directory, finalizes provenance and
    reference manifests, fully validates the staged bundle, and publishes
    via a native no-replace exclusive rename only when ``bundle_root`` is
    absent.

    Raises :class:`LanhuFigmaError` on any failure. On failure, all
    staging residue is removed. If the operation published the bundle but
    a subsequent step (parent fsync, report finalization) fails, the
    published bundle is also rolled back. A pre-existing final bundle is
    never overwritten, even if identical.
    """
    _parse_locator(locator)
    _verify_capsule()
    board_ref = _board_ref(locator)
    bundle_root = Path(os.path.abspath(str(bundle_root)))
    # Reject the final path or any existing path-chain component that is a
    # symlink, before any staging directory is created. This early check is
    # a fast diagnostic only; the native exclusive rename is the decisive
    # publication gate.
    _check_path_chain_no_symlink(bundle_root, "bundle-root")
    if bundle_root.exists() or bundle_root.is_symlink():
        raise LanhuFigmaError(
            f"bundle_root exists; refusing overwrite: {bundle_root}"
        )
    parent = bundle_root.parent
    if not parent.exists():
        raise LanhuFigmaError(
            f"bundle_root parent does not exist: {parent}"
        )
    _check_regular_dir(parent, "bundle-root-parent")
    staging = Path(
        tempfile.mkdtemp(prefix=".lanhu_figma_v1_stage.", dir=str(parent))
    )
    published_by_us = False
    try:
        _run_seven_steps(locator, staging)
        report = _finalize_bundle(staging, locator=locator, board_ref=board_ref)
        # Native exclusive rename — the decisive publication gate. No
        # check-then-rename race window. EEXIST/ENOTEMPTY surface as
        # LanhuFigmaError (destination already present).
        _atomic_publish_no_replace(staging, bundle_root)
        published_by_us = True
        # Durably fsync the parent directory so the rename survives a crash.
        # Convert OSError to LanhuFigmaError so the rollback path can
        # cleanly roll back the published bundle and re-raise visibly.
        try:
            _fsync_dir(parent)
        except OSError as exc:
            err_no = getattr(exc, "errno", None)
            if err_no is not None:
                raise LanhuFigmaError(
                    f"parent fsync failed: OSError errno={err_no}"
                ) from exc
            raise LanhuFigmaError("parent fsync failed: OSError") from exc
        report_payload = dict(report)
        report_payload["bundle_root"] = str(bundle_root)
        return report_payload
    except BaseException as original:
        # Remove all staging residue on every failure. If this process
        # published the bundle and a subsequent step (fsync, report
        # finalization) failed, roll back the bundle too. Cleanup failures
        # are converted to stable, secret-safe errors and never swallowed.
        if published_by_us:
            try:
                shutil.rmtree(bundle_root)
            except BaseException as cleanup_exc:
                raise LanhuFigmaError(
                    "rollback remove failed after "
                    f"{type(original).__name__}: {type(cleanup_exc).__name__}"
                ) from original
            try:
                _fsync_dir(parent)
            except BaseException as cleanup_exc:
                raise LanhuFigmaError(
                    "rollback parent fsync failed after "
                    f"{type(original).__name__}: {type(cleanup_exc).__name__}"
                ) from original
        if staging.exists() or staging.is_symlink():
            try:
                shutil.rmtree(staging)
            except BaseException as cleanup_exc:
                raise LanhuFigmaError(
                    "staging cleanup failed after "
                    f"{type(original).__name__}: {type(cleanup_exc).__name__}"
                ) from original
        raise


# ---------------------------------------------------------------------------
# verify_bundle: strict closed verification of a published bundle.
# ---------------------------------------------------------------------------


def _build_report_from_bundle(
    bundle_root: Path,
    *,
    board_ref: str,
    locator: str,
) -> dict[str, Any]:
    """Build a canonical ``design_bundle_report.v1`` from a verified bundle.

    Does NOT mutate the bundle. Assumes ``_verify_bundle_payload`` has
    already validated the layout.
    """
    artifacts: dict[str, str] = {}
    for name in REQUIRED_TOPLEVEL_ARTIFACTS:
        artifacts[name] = _sha256_file(bundle_root / name)
    assets_inventory = _inventory_assets(bundle_root / ASSETS_DIR_NAME)
    return {
        "ok": True,
        "kind": KIND_REPORT,
        "schema_version": SCHEMA_VERSION,
        "source_id": SOURCE_ID,
        "board_ref": board_ref,
        "locator": locator,
        "artifacts": artifacts,
        "assets_inventory": assets_inventory,
    }


def _verify_bundle_payload(bundle_root: Path) -> tuple[str, str]:
    """Strict verification of a published bundle layout.

    Returns ``(board_ref, locator)`` on success. Raises
    :class:`LanhuFigmaError` on any violation.
    """
    _check_path_chain_no_symlink(bundle_root, "bundle-root")
    _check_regular_dir(bundle_root, "bundle-root")

    # Top-level entry set must be exactly the required set.
    expected_top = set(REQUIRED_TOPLEVEL_ARTIFACTS) | {
        PROVENANCE_NAME,
        ASSETS_DIR_NAME,
    }
    actual_top: set[str] = set()
    for entry in bundle_root.iterdir():
        if entry.is_symlink():
            raise LanhuFigmaError(
                f"top-level entry is a symlink: {entry.name}"
            )
        actual_top.add(entry.name)
    missing = expected_top - actual_top
    extra = actual_top - expected_top
    if missing or extra:
        raise LanhuFigmaError(
            f"top-level entry mismatch: missing={sorted(missing)} extra={sorted(extra)}"
        )

    # assets/ directory must be a regular directory.
    _check_regular_dir(bundle_root / ASSETS_DIR_NAME, "assets dir")
    # The legacy assets/manifest.json is mandatory.
    legacy = bundle_root / ASSETS_DIR_NAME / LEGACY_ASSETS_MANIFEST_NAME
    _check_regular_file(legacy, "assets/manifest.json")
    _decode_json_strict_any(legacy.read_bytes(), "assets/manifest.json")

    # Load provenance first; it carries board_ref / locator / digests.
    prov_path = bundle_root / PROVENANCE_NAME
    _check_regular_file(prov_path, PROVENANCE_NAME)
    prov = _decode_json_strict(prov_path.read_bytes(), PROVENANCE_NAME)
    if prov.get("kind") != KIND_PROVENANCE:
        raise LanhuFigmaError(
            f"provenance kind mismatch: {prov.get('kind')!r}"
        )
    if prov.get("schema_version") != SCHEMA_VERSION:
        raise LanhuFigmaError(
            f"provenance schema_version mismatch: {prov.get('schema_version')!r}"
        )
    if prov.get("source_id") != SOURCE_ID:
        raise LanhuFigmaError(
            f"provenance source_id mismatch: {prov.get('source_id')!r}"
        )
    if prov.get("ir_schema") != IR_SCHEMA:
        raise LanhuFigmaError(
            f"provenance ir_schema mismatch: {prov.get('ir_schema')!r}"
        )
    board_ref = prov.get("board_ref")
    locator = prov.get("locator")
    if not isinstance(board_ref, str) or not board_ref:
        raise LanhuFigmaError("provenance missing board_ref")
    if not isinstance(locator, str) or not locator:
        raise LanhuFigmaError("provenance missing locator")
    # board_ref must match a fresh resolve of the stored locator.
    expected_board_ref = _board_ref(locator)
    if board_ref != expected_board_ref:
        raise LanhuFigmaError(
            f"provenance board_ref mismatch: stored={board_ref!r} "
            f"expected={expected_board_ref!r}"
        )

    artifacts = prov.get("artifacts")
    if not isinstance(artifacts, dict):
        raise LanhuFigmaError("provenance artifacts missing")
    for name in REQUIRED_TOPLEVEL_ARTIFACTS:
        digest = artifacts.get(name)
        if not isinstance(digest, str) or len(digest) != 64:
            raise LanhuFigmaError(
                f"provenance missing valid digest for artifact: {name}"
            )

    # Each required top-level artifact: regular file, no symlink, strict
    # JSON where applicable, and SHA matches provenance.
    for name in REQUIRED_TOPLEVEL_ARTIFACTS:
        path = bundle_root / name
        _check_regular_file(path, f"artifact {name}")
        if name in JSON_TOPLEVEL_ARTIFACTS:
            _decode_json_strict(path.read_bytes(), f"artifact {name}")
        actual_sha = _sha256_file(path)
        if actual_sha != artifacts[name]:
            raise LanhuFigmaError(
                f"digest mismatch for {name}: "
                f"provenance={artifacts[name]} actual={actual_sha}"
            )

    # reference.png + reference_manifest.json dimensions/SHA binding.
    ref_path = bundle_root / "reference.png"
    ref_w, ref_h = _png_size(ref_path)
    rm_path = bundle_root / REFERENCE_MANIFEST_NAME
    rm = _decode_json_strict(rm_path.read_bytes(), REFERENCE_MANIFEST_NAME)
    if rm.get("kind") != KIND_REFERENCE_MANIFEST:
        raise LanhuFigmaError(
            f"reference_manifest kind mismatch: {rm.get('kind')!r}"
        )
    if rm.get("schema_version") != SCHEMA_VERSION:
        raise LanhuFigmaError(
            f"reference_manifest schema_version mismatch: "
            f"{rm.get('schema_version')!r}"
        )
    if rm.get("reference") != "reference.png":
        raise LanhuFigmaError(
            f"reference_manifest reference mismatch: {rm.get('reference')!r}"
        )
    if rm.get("sha256") != _sha256_file(ref_path):
        raise LanhuFigmaError("reference_manifest sha256 mismatch")
    if rm.get("width") != ref_w or rm.get("height") != ref_h:
        raise LanhuFigmaError(
            f"reference_manifest dimensions mismatch: "
            f"stored=({rm.get('width')},{rm.get('height')}) "
            f"actual=({ref_w},{ref_h})"
        )

    # raw.json must contain figma_json.artboard.
    raw_obj = _decode_json_strict(
        (bundle_root / "raw.json").read_bytes(), "raw.json"
    )
    figma = raw_obj.get("figma_json")
    if not isinstance(figma, dict) or not isinstance(figma.get("artboard"), dict):
        raise LanhuFigmaError("raw.json missing figma_json.artboard")

    # Reference PNG dimensions must match raw artboard bbox within 1.0.
    _check_reference_matches_artboard(ref_w, ref_h, raw_obj)

    # scene.json sourceSchema must be lanhu_figma_json.
    scene_obj = _decode_json_strict(
        (bundle_root / "scene.json").read_bytes(), "scene.json"
    )
    if scene_obj.get("sourceSchema") != IR_SCHEMA:
        raise LanhuFigmaError(
            f"scene.json sourceSchema not {IR_SCHEMA}: "
            f"{scene_obj.get('sourceSchema')!r}"
        )

    # assets/ inventory must match provenance exactly.
    expected_inv = prov.get("assets_inventory")
    if not isinstance(expected_inv, list):
        raise LanhuFigmaError("provenance assets_inventory missing")
    expected_pairs = [
        [row[0], row[1]] if isinstance(row, list) and len(row) == 2 else None
        for row in expected_inv
    ]
    if any(p is None for p in expected_pairs):
        raise LanhuFigmaError("provenance assets_inventory malformed")
    actual_inv = _inventory_assets(bundle_root / ASSETS_DIR_NAME)
    if actual_inv != expected_pairs:
        raise LanhuFigmaError(
            f"asset inventory mismatch: "
            f"expected={expected_pairs} actual={actual_inv}"
        )

    return board_ref, locator


def verify_bundle(bundle_root: Path) -> dict[str, Any]:
    """Verify a published bundle and emit a canonical report.

    Verifies the installed capsule first (so a tampered environment is
    detected before reading user-supplied data), then strictly verifies
    the bundle layout, digests, PNG, scene schema, provenance/board-ref
    binding, and asset inventory.
    """
    _verify_capsule()
    bundle_root = Path(os.path.abspath(str(bundle_root)))
    board_ref, locator = _verify_bundle_payload(bundle_root)
    report = _build_report_from_bundle(
        bundle_root, board_ref=board_ref, locator=locator
    )
    report_payload = dict(report)
    report_payload["bundle_root"] = str(bundle_root)
    return report_payload


# ---------------------------------------------------------------------------
# probe: verify capsule + verify auth/network can obtain raw artboard +
# reference PNG. Uses only temporary storage.
# ---------------------------------------------------------------------------


def probe(locator: str) -> dict[str, Any]:
    """Verify capsule + verify auth/network access via the fixed capsule
    primitives ``fetch.py`` and ``download_cover.py``.

    Uses only temporary storage; never mutates the task CSV, project root,
    or any final bundle root. Removes all temporary artifacts on success
    and failure.
    """
    _parse_locator(locator)
    capsule = _verify_capsule()
    board_ref = _board_ref(locator)
    probe_parent = Path(tempfile.gettempdir())
    with tempfile.TemporaryDirectory(
        prefix=".lanhu_figma_probe.", dir=str(probe_parent)
    ) as tmp:
        stage = Path(tmp)
        _run_step(
            "fetch.py",
            ["--url", locator, "--output", str(stage / "raw.json")],
        )
        _run_step(
            "download_cover.py",
            ["--url", locator, "--out", str(stage / "reference.png")],
        )
        raw_path = stage / "raw.json"
        ref_path = stage / "reference.png"
        _check_regular_file(raw_path, "probe raw.json")
        _check_regular_file(ref_path, "probe reference.png")
        raw_obj = _decode_json_strict(raw_path.read_bytes(), "probe raw.json")
        figma = raw_obj.get("figma_json")
        if not isinstance(figma, dict) or not isinstance(figma.get("artboard"), dict):
            raise LanhuFigmaError("probe raw.json missing figma_json.artboard")
        width, height = _png_size(ref_path)
        _check_reference_matches_artboard(width, height, raw_obj)
        probe_payload = {
            "raw_artboard_present": True,
            "reference_png_present": True,
            "reference_png_width": width,
            "reference_png_height": height,
        }
    return {
        "ok": True,
        "kind": KIND_PROBE,
        "schema_version": SCHEMA_VERSION,
        "source_id": SOURCE_ID,
        "board_ref": board_ref,
        "locator": locator,
        "capsule": capsule,
        "probe": probe_payload,
    }


# ---------------------------------------------------------------------------
# CLI (one canonical JSON object; no traceback; no override flags).
# ---------------------------------------------------------------------------


class _JSONArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that raises LanhuFigmaError instead of exiting."""

    def error(self, message: str) -> None:  # type: ignore[override]
        raise LanhuFigmaError(f"cli: {message}")


def _emit(stream, payload: dict[str, Any]) -> None:
    stream.write(_canonical_json_bytes(payload).decode("utf-8"))
    stream.flush()


def _build_parser() -> _JSONArgumentParser:
    parser = _JSONArgumentParser(
        prog=SCRIPT_NAME,
        description="ICP P2b lanhu-figma DesignSource wrapper.",
        add_help=True,
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    p_resolve = sub.add_parser("resolve", add_help=True)
    p_resolve.add_argument("--locator", required=True)

    p_probe = sub.add_parser("probe", add_help=True)
    p_probe.add_argument("--locator", required=True)

    p_fetch = sub.add_parser("fetch-normalize", add_help=True)
    p_fetch.add_argument("--locator", required=True)
    p_fetch.add_argument(
        "--bundle-root",
        required=True,
        type=lambda p: Path(p).expanduser(),
    )

    p_verify = sub.add_parser("verify-bundle", add_help=True)
    p_verify.add_argument(
        "--bundle-root",
        required=True,
        type=lambda p: Path(p).expanduser(),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    raw = sys.argv[1:] if argv is None else list(argv)
    try:
        parser = _build_parser()
        args = parser.parse_args(raw)
        if args.subcommand == "resolve":
            board_ref = resolve(args.locator)
            _emit(
                sys.stdout,
                {
                    "ok": True,
                    "kind": "design_source_resolve.v1",
                    "schema_version": SCHEMA_VERSION,
                    "source_id": SOURCE_ID,
                    "locator": args.locator,
                    "board_ref": board_ref,
                },
            )
            return 0
        if args.subcommand == "probe":
            report = probe(args.locator)
            _emit(sys.stdout, report)
            return 0
        if args.subcommand == "fetch-normalize":
            report = fetch_normalize(args.locator, args.bundle_root)
            _emit(sys.stdout, report)
            return 0
        if args.subcommand == "verify-bundle":
            report = verify_bundle(args.bundle_root)
            _emit(sys.stdout, report)
            return 0
        raise LanhuFigmaError(f"cli: unknown subcommand: {args.subcommand!r}")
    except LanhuFigmaError as exc:
        _emit(
            sys.stderr,
            {"ok": False, "code": CODE_DESIGN, "message": str(exc)},
        )
        return 2
    except Exception as exc:  # noqa: BLE001
        _emit(
            sys.stderr,
            {
                "ok": False,
                "code": CODE_DESIGN,
                "message": type(exc).__name__,
            },
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
