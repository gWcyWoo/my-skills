#!/usr/bin/env python3
"""ICP P2c Flutter platform-adapter descriptor (non-executable).

This module is a **descriptor only**. It structures the existing vendored
iFF Flutter-specific script families under the nine settled platform
operation ports, binds every mapped primitive to the immutable capsule
manifest SHA-256, and remains fail-closed / inactive until later
executable builders and parity gates are complete.

Public Python API:

* ``describe() -> dict`` — verify the installed vendored capsule first
  (using the existing fixed verifier derived from this module's installed
  location), then return the canonical, byte-for-byte deterministic
  descriptor of kind ``icp.platform-adapter-descriptor.v1``.
* ``verify_descriptor() -> dict`` — verify the installed capsule first,
  build the canonical descriptor, fail-closed validate every invariant,
  and return a verification report of kind
  ``icp.platform-adapter-descriptor-verify.v1``.

CLI:

* ``describe`` — emit exactly one canonical JSON object on stdout
  (exit 0) for success, or one canonical JSON object on stderr (exit 2)
  for failure. No traceback, no arbitrary exception text.
* ``verify`` — same discipline as ``describe`` for the verification
  report.

Locked boundaries:

* Descriptor only. Root ``executable`` is ``false``;
  ``activation_state`` is ``inactive``; no operation may carry an
  executable/command/argv/shell/script-runner field. No executable
  builder, Dart generation, packaging, capture, parity gate, claim, or
  registry mutation runs here.
* Production code derives ICP root, capsule root, manifest path, and
  registry path only from this module's installed file location. No
  public override is exposed for skill root, capsule root, manifest
  path, registry path, command, executable, script, interpreter,
  runner, environment, argv, or activation.
* Every public operation verifies the installed vendored capsule first,
  using the existing fixed verifier derived from installed ICP paths.
  No sibling ``iff/`` dependency is allowed: this module never imports,
  reads, executes, or follows a symlink into ``iff/**``.
* The ownership mapping is a fixed private code constant. SHA values are
  resolved from the installed ``iff-v1-vendor.json`` only after capsule
  verification.
* Only the Python standard library is used.
* ``describe()`` and ``verify_descriptor()`` are deterministic
  byte-for-byte across processes and working directories.

Local error code is ``platform_adapter_descriptor_failed``, scoped to
this descriptor; it never extends ``icp_common.ALL_ERROR_CODES``.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Public schema constants.
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1
KIND_DESCRIPTOR = "icp.platform-adapter-descriptor.v1"
KIND_VERIFY = "icp.platform-adapter-descriptor-verify.v1"
PLATFORM_ID = "flutter"
PROFILE_ID = "flutter-standard"
ACTIVATION_STATE = "inactive"
SCRIPT_NAME = "flutter_standard_v1.py"

# Local error code. This is NOT an ICP pre-claim code and does not
# extend icp_common.ALL_ERROR_CODES.
CODE_DESCRIPTOR = "platform_adapter_descriptor_failed"

# ---------------------------------------------------------------------------
# Fixed production paths derived from this module's installed location.
# Accepts NO override; this is the runtime surface.
# ---------------------------------------------------------------------------

ICP_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ICP_ROOT / "references" / "baselines" / "iff-v1-vendor.json"
REGISTRY_PATH = ICP_ROOT / "references" / "registries.json"
VERIFY_TOOL = ICP_ROOT / "scripts" / "verify_vendor_iff_v1.py"


class DescriptorError(ValueError):
    """A local platform-adapter-descriptor failure.

    Raised for any capsule verification error, manifest load/shape error,
    descriptor build/validate error, or CLI usage error. The CLI catches
    this and emits one canonical JSON error object.
    """


# ---------------------------------------------------------------------------
# Fixed private ownership mapping (the source of truth).
#
# Order of operations is fixed and matches the settled registry exactly:
# project_preflight, visible_codegen, fixture_codegen, trace_harness,
# packaging, test_runner, runtime_capture, project_gates, fan_in.
#
# Each entry pins:
#   - id                       (the settled platform operation port id)
#   - capability_state         (from the settled registry)
#   - implementation_state     (new-port-required | legacy-mapped)
#   - legacy_primitives        (tuple of vendored script basenames)
#
# project_preflight has no legacy primitive; ``sync_project_rules.py`` is
# explicitly NOT a platform port and must not appear here. SharedCore
# scripts (render fidelity, responsive comparison, visual diff,
# expected/slots, contract parsing, prompt/supervisor orchestration) do
# not belong in this platform descriptor.
# ---------------------------------------------------------------------------

_CAP_REQUIRED = "required"
_CAP_OPTIONAL_SHARED = "optional-with-shared-policy"
_IMPL_NEW_PORT = "new-port-required"
_IMPL_LEGACY_MAPPED = "legacy-mapped"

_OPERATIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "project_preflight",
        "capability_state": _CAP_REQUIRED,
        "implementation_state": _IMPL_NEW_PORT,
        "legacy_primitives": (),
    },
    {
        "id": "visible_codegen",
        "capability_state": _CAP_REQUIRED,
        "implementation_state": _IMPL_LEGACY_MAPPED,
        "legacy_primitives": (
            "generate_canvas.py",
            "make_implementation_map.py",
            "make_status_bar_policy.py",
        ),
    },
    {
        "id": "fixture_codegen",
        "capability_state": _CAP_REQUIRED,
        "implementation_state": _IMPL_LEGACY_MAPPED,
        "legacy_primitives": ("make_visual_fixture.py",),
    },
    {
        "id": "trace_harness",
        "capability_state": _CAP_OPTIONAL_SHARED,
        "implementation_state": _IMPL_LEGACY_MAPPED,
        # P2.5d: trace_harness legacy primitive tuple is now ordered
        # (merge_shared_expected.py, gen_layout_trace_test.py) to mirror
        # the trusted plan's capsule steps. The platform-origin
        # provenance gate (flutter_merged_expectation_provenance_gate_v1.py)
        # is NOT a legacy primitive and must not appear here.
        "legacy_primitives": (
            "merge_shared_expected.py",
            "gen_layout_trace_test.py",
        ),
    },
    {
        "id": "packaging",
        "capability_state": _CAP_REQUIRED,
        "implementation_state": _IMPL_LEGACY_MAPPED,
        "legacy_primitives": (
            "prepare_assembly_packaging.py",
            "update_pubspec_assets.py",
            "copy_assets.py",
        ),
    },
    {
        "id": "test_runner",
        "capability_state": _CAP_REQUIRED,
        "implementation_state": _IMPL_LEGACY_MAPPED,
        "legacy_primitives": (
            "assembly_tdd_guard.py",
            "retire_stale_flutter_template_tests.py",
        ),
    },
    {
        "id": "runtime_capture",
        "capability_state": _CAP_OPTIONAL_SHARED,
        "implementation_state": _IMPL_LEGACY_MAPPED,
        "legacy_primitives": (
            "select_runtime_device.py",
            "device_lock.py",
            "capture_runtime_screenshot.py",
            "physical_device_preview.py",
        ),
    },
    {
        "id": "project_gates",
        "capability_state": _CAP_REQUIRED,
        "implementation_state": _IMPL_LEGACY_MAPPED,
        "legacy_primitives": (
            "check_interaction_wiring.py",
            "check_api_integration.py",
            "check_fixture_source.py",
            "check_capture_readiness.py",
        ),
    },
    {
        "id": "fan_in",
        "capability_state": _CAP_REQUIRED,
        "implementation_state": _IMPL_LEGACY_MAPPED,
        "legacy_primitives": (
            "assembly_plan_batch.py",
            "assembly_worker_supervisor.py",
            "check_done_gate.py",
            "assembly_completion.py",
        ),
    },
)

_OPERATION_IDS: tuple[str, ...] = tuple(op["id"] for op in _OPERATIONS)

# Fields forbidden anywhere except the documented root ``executable`` key.
# These names would re-introduce an executable surface; their presence on
# any operation or primitive is an integrity violation.
_EXECUTABLE_FIELD_NAMES = frozenset(
    {
        "command",
        "argv",
        "shell",
        "interpreter",
        "env",
        "runner",
        "args",
        "program",
        "cmd",
        "subprocess",
        "exec",
        "run",
        "script_path",
        "script_runner",
        "activate",
        "activation_command",
    }
)


# ---------------------------------------------------------------------------
# Small deterministic helpers (canonical JSON, digests, strict decode).
# ---------------------------------------------------------------------------


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    for key, _value in pairs:
        if key in seen:
            raise DescriptorError(f"duplicate JSON key: {key!r}")
        seen.add(key)
    return dict(pairs)


def _decode_json_strict(raw: bytes, role: str) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DescriptorError(f"{role}: not UTF-8: {exc}") from exc
    try:
        obj = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise DescriptorError(f"{role}: not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise DescriptorError(
            f"{role}: root must be a JSON object, got {type(obj).__name__}"
        )
    return obj


def _check_regular_file(path: Path, role: str) -> None:
    """Refuse symlinks / non-regular / unreadable files."""
    try:
        if path.is_symlink():
            raise DescriptorError(f"{role}: refusing symlink: {path}")
        st = path.lstat()
    except OSError as exc:
        raise DescriptorError(f"{role}: cannot lstat {path}: {exc}") from exc
    if not stat.S_ISREG(st.st_mode):
        raise DescriptorError(f"{role}: not a regular file: {path}")
    if not os.access(path, os.R_OK):
        raise DescriptorError(f"{role}: unreadable file: {path}")


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
    return name.endswith(".py")


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
            "verify_vendor_iff_v1_p2c", str(VERIFY_TOOL)
        )
        if spec is None or spec.loader is None:
            raise DescriptorError("cannot load verify_vendor_iff_v1 module spec")
        module = importlib.util.module_from_spec(spec)
        sys.modules["verify_vendor_iff_v1_p2c"] = module
        spec.loader.exec_module(module)
        _VERIFY_MODULE = module
    return _VERIFY_MODULE


def _verify_capsule() -> dict[str, Any]:
    """Verify the installed vendored capsule via the P2a runtime gate.

    Returns the canonical capsule-success payload. Any integrity violation
    surfaces as a :class:`DescriptorError`. Never imports, reads, executes,
    or follows a symlink into ``iff/**``.
    """
    module = _load_verify_module()
    try:
        return module.verify_skill(ICP_ROOT)
    except module.CapsuleIntegrityError as exc:
        raise DescriptorError(f"capsule verification failed: {exc}") from exc
    except Exception as exc:
        raise DescriptorError(
            f"capsule verification raised {type(exc).__name__}"
        ) from exc


# ---------------------------------------------------------------------------
# Manifest load + shape validation.
#
# The capsule verifier already integrity-gates the manifest bytes; the
# checks below are an additional local layer that ensures the manifest we
# read for SHA lookup is structurally well-formed for descriptor use.
# ---------------------------------------------------------------------------


def _load_manifest() -> dict[str, Any]:
    _check_regular_file(MANIFEST_PATH, "iff-v1-vendor.json")
    manifest = _decode_json_strict(MANIFEST_PATH.read_bytes(), "iff-v1-vendor.json")
    if manifest.get("kind") != "icp.iff-v1-vendor-capsule":
        raise DescriptorError(
            f"manifest kind not canonical: {manifest.get('kind')!r}"
        )
    if manifest.get("schema_version") != 1:
        raise DescriptorError(
            f"manifest schema_version not canonical: "
            f"{manifest.get('schema_version')!r}"
        )
    if manifest.get("capsule_root") != "vendor/iff_v1":
        raise DescriptorError(
            f"manifest capsule_root not canonical: "
            f"{manifest.get('capsule_root')!r}"
        )
    scripts = manifest.get("scripts")
    if not isinstance(scripts, list) or not scripts:
        raise DescriptorError("manifest scripts missing/empty")
    return manifest


def _manifest_sha_map(manifest: dict[str, Any]) -> dict[str, str]:
    """Map basename -> sha256 from the manifest's scripts list.

    Rejects duplicates, unsafe names, and malformed SHAs up front so the
    descriptor builder never sees an ambiguous lookup.
    """
    out: dict[str, str] = {}
    for entry in manifest["scripts"]:
        if not isinstance(entry, dict):
            raise DescriptorError("manifest script entry not an object")
        name = entry.get("name")
        if not _is_safe_basename(name):
            raise DescriptorError(f"manifest script name unsafe: {name!r}")
        if name in out:
            raise DescriptorError(f"manifest script duplicate: {name!r}")
        sha = entry.get("sha256")
        if not _is_sha256_hex(sha):
            raise DescriptorError(
                f"manifest script {name} sha256 malformed: {sha!r}"
            )
        out[name] = sha
    return out


# ---------------------------------------------------------------------------
# Registry cross-check (defensive; the descriptor embeds the same values).
# ---------------------------------------------------------------------------


def _load_registry() -> dict[str, Any]:
    _check_regular_file(REGISTRY_PATH, "registries.json")
    registry = _decode_json_strict(REGISTRY_PATH.read_bytes(), "registries.json")
    if registry.get("kind") != "icp-p1a-registries":
        raise DescriptorError(
            f"registry kind not canonical: {registry.get('kind')!r}"
        )
    return registry


# ---------------------------------------------------------------------------
# Descriptor build + validate.
# ---------------------------------------------------------------------------


def _build_descriptor(manifest: dict[str, Any]) -> dict[str, Any]:
    """Build the canonical descriptor from the fixed mapping + manifest.

    The manifest is already capsule-verified; this function only looks up
    SHAs by basename. Raises :class:`DescriptorError` if any mapped
    primitive basename is absent from the manifest.
    """
    sha_map = _manifest_sha_map(manifest)
    operations: list[dict[str, Any]] = []
    for op in _OPERATIONS:
        primitives: list[dict[str, Any]] = []
        for script_name in op["legacy_primitives"]:
            if script_name not in sha_map:
                raise DescriptorError(
                    f"primitive {script_name!r} missing from manifest"
                )
            primitives.append(
                {
                    "script": script_name,
                    "sha256": sha_map[script_name],
                }
            )
        operations.append(
            {
                "id": op["id"],
                "capability_state": op["capability_state"],
                "implementation_state": op["implementation_state"],
                "legacy_primitives": primitives,
            }
        )
    return {
        "kind": KIND_DESCRIPTOR,
        "schema_version": SCHEMA_VERSION,
        "platform_id": PLATFORM_ID,
        "profile_id": PROFILE_ID,
        "activation_state": ACTIVATION_STATE,
        "executable": False,
        "operations": operations,
    }


def _reject_executable_fields(obj: Any, location: str, allow_root_executable: bool) -> None:
    """Walk ``obj`` and reject any forbidden executable/command/argv/shell
    field. The single permitted executable surface is the root
    ``executable`` key (which must equal ``False``)."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            here = f"{location}/{key}" if location else key
            if key == "executable":
                if not allow_root_executable:
                    raise DescriptorError(
                        f"executable field outside root: {here}"
                    )
                if value is not False:
                    raise DescriptorError(
                        f"root executable must be false: {here}={value!r}"
                    )
                continue
            if key in _EXECUTABLE_FIELD_NAMES:
                raise DescriptorError(f"forbidden executable field: {here}")
            _reject_executable_fields(value, here, allow_root_executable=False)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _reject_executable_fields(item, f"{location}[{i}]", allow_root_executable=False)


def _validate_descriptor_against_spec(
    descriptor: dict[str, Any], manifest: dict[str, Any]
) -> None:
    """Fail-closed validation of the descriptor against the fixed mapping
    and the installed manifest.

    Rejects: wrong kind/schema/platform/profile/activation/executable;
    unexpected top-level keys; duplicate JSON keys (caught at decode);
    missing/extra operations; wrong operation order; duplicate operation
    IDs; wrong capability state; wrong implementation state; missing/
    extra primitives per operation; wrong primitive order; non-basename
    script names; missing/extra/malformed SHA-256; manifest SHA mismatch;
    duplicate primitive ownership across operations; any executable/
    command/argv/shell field anywhere except the root ``executable`` key.
    """
    # Top-level shape.
    if descriptor.get("kind") != KIND_DESCRIPTOR:
        raise DescriptorError(
            f"descriptor kind mismatch: {descriptor.get('kind')!r}"
        )
    if descriptor.get("schema_version") != SCHEMA_VERSION:
        raise DescriptorError(
            f"descriptor schema_version mismatch: "
            f"{descriptor.get('schema_version')!r}"
        )
    if descriptor.get("platform_id") != PLATFORM_ID:
        raise DescriptorError(
            f"descriptor platform_id mismatch: "
            f"{descriptor.get('platform_id')!r}"
        )
    if descriptor.get("profile_id") != PROFILE_ID:
        raise DescriptorError(
            f"descriptor profile_id mismatch: "
            f"{descriptor.get('profile_id')!r}"
        )
    if descriptor.get("activation_state") != ACTIVATION_STATE:
        raise DescriptorError(
            f"descriptor activation_state mismatch: "
            f"{descriptor.get('activation_state')!r}"
        )
    if descriptor.get("executable") is not False:
        raise DescriptorError(
            f"descriptor executable must be false: "
            f"{descriptor.get('executable')!r}"
        )

    expected_top_keys = {
        "kind",
        "schema_version",
        "platform_id",
        "profile_id",
        "activation_state",
        "executable",
        "operations",
    }
    actual_top_keys = set(descriptor.keys())
    if actual_top_keys != expected_top_keys:
        extra = actual_top_keys - expected_top_keys
        missing = expected_top_keys - actual_top_keys
        raise DescriptorError(
            f"descriptor top-level keys mismatch: "
            f"extra={sorted(extra)} missing={sorted(missing)}"
        )

    # Reject any executable/command/argv/shell field anywhere (root
    # executable=false is the only permitted executable surface).
    _reject_executable_fields(descriptor, "", allow_root_executable=True)

    operations = descriptor["operations"]
    if not isinstance(operations, list):
        raise DescriptorError("descriptor operations not a list")
    if len(operations) != len(_OPERATIONS):
        raise DescriptorError(
            f"descriptor operations count mismatch: "
            f"got {len(operations)} expected {len(_OPERATIONS)}"
        )

    # Per-operation shape + content.
    sha_map = _manifest_sha_map(manifest)
    seen_primitives: set[str] = set()
    seen_op_ids: set[str] = set()
    for index, op_dict in enumerate(operations):
        if not isinstance(op_dict, dict):
            raise DescriptorError(
                f"operation[{index}] not an object"
            )
        expected = _OPERATIONS[index]
        expected_op_keys = {
            "id",
            "capability_state",
            "implementation_state",
            "legacy_primitives",
        }
        actual_op_keys = set(op_dict.keys())
        if actual_op_keys != expected_op_keys:
            extra = actual_op_keys - expected_op_keys
            missing = expected_op_keys - actual_op_keys
            raise DescriptorError(
                f"operation[{index}] keys mismatch: "
                f"extra={sorted(extra)} missing={sorted(missing)}"
            )
        op_id = op_dict["id"]
        if not isinstance(op_id, str) or op_id != expected["id"]:
            raise DescriptorError(
                f"operation[{index}] id mismatch: "
                f"got {op_id!r} expected {expected['id']!r}"
            )
        if op_id in seen_op_ids:
            raise DescriptorError(f"duplicate operation id: {op_id!r}")
        seen_op_ids.add(op_id)
        if op_dict["capability_state"] != expected["capability_state"]:
            raise DescriptorError(
                f"operation {op_id} capability_state mismatch: "
                f"got {op_dict['capability_state']!r} "
                f"expected {expected['capability_state']!r}"
            )
        if op_dict["implementation_state"] != expected["implementation_state"]:
            raise DescriptorError(
                f"operation {op_id} implementation_state mismatch: "
                f"got {op_dict['implementation_state']!r} "
                f"expected {expected['implementation_state']!r}"
            )
        # project_preflight is new-port-required: it must have no legacy
        # primitive. sync_project_rules.py is explicitly NOT a platform
        # port and must not appear here or anywhere else.
        primitives = op_dict["legacy_primitives"]
        if not isinstance(primitives, list):
            raise DescriptorError(
                f"operation {op_id} legacy_primitives not a list"
            )
        expected_prims = expected["legacy_primitives"]
        if len(primitives) != len(expected_prims):
            raise DescriptorError(
                f"operation {op_id} primitive count mismatch: "
                f"got {len(primitives)} expected {len(expected_prims)}"
            )
        for prim_index, prim in enumerate(primitives):
            if not isinstance(prim, dict):
                raise DescriptorError(
                    f"operation {op_id} primitive[{prim_index}] not an object"
                )
            if set(prim.keys()) != {"script", "sha256"}:
                raise DescriptorError(
                    f"operation {op_id} primitive[{prim_index}] keys mismatch: "
                    f"{sorted(prim.keys())}"
                )
            script_name = prim["script"]
            expected_name = expected_prims[prim_index]
            if not _is_safe_basename(script_name):
                raise DescriptorError(
                    f"operation {op_id} primitive[{prim_index}] "
                    f"unsafe script name: {script_name!r}"
                )
            if script_name != expected_name:
                raise DescriptorError(
                    f"operation {op_id} primitive[{prim_index}] "
                    f"script mismatch: got {script_name!r} "
                    f"expected {expected_name!r}"
                )
            if script_name == "sync_project_rules.py":
                raise DescriptorError(
                    "sync_project_rules.py must not be mapped: "
                    "project_rules is not a platform port"
                )
            if script_name not in sha_map:
                raise DescriptorError(
                    f"operation {op_id} primitive {script_name} "
                    f"missing from manifest"
                )
            sha_value = prim["sha256"]
            if not _is_sha256_hex(sha_value):
                raise DescriptorError(
                    f"operation {op_id} primitive {script_name} "
                    f"sha256 malformed: {sha_value!r}"
                )
            if sha_value != sha_map[script_name]:
                raise DescriptorError(
                    f"operation {op_id} primitive {script_name} "
                    f"sha256 mismatch: descriptor={sha_value} "
                    f"manifest={sha_map[script_name]}"
                )
            if script_name in seen_primitives:
                raise DescriptorError(
                    f"duplicate primitive ownership: {script_name}"
                )
            seen_primitives.add(script_name)

    # Operation order is decisive (duplicates already rejected above).
    actual_ids = [op["id"] for op in operations]
    if actual_ids != list(_OPERATION_IDS):
        raise DescriptorError(
            f"operation ids/order mismatch: got {actual_ids}"
        )


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------


def describe() -> dict[str, Any]:
    """Verify the installed vendored capsule and return the canonical
    Flutter ``flutter-standard`` platform-adapter descriptor.

    The descriptor is descriptor-only (``executable=false`` and
    ``activation_state=inactive``); it never executes a primitive. The
    returned dict is byte-for-byte deterministic across processes and
    working directories when canonicalized via
    :func:`_canonical_json_bytes`.
    """
    _verify_capsule()
    manifest = _load_manifest()
    return _build_descriptor(manifest)


def verify_descriptor() -> dict[str, Any]:
    """Verify the installed capsule, build the canonical descriptor, and
    fail-closed validate every invariant against the fixed mapping and
    the installed manifest.

    Returns a verification report of kind
    ``icp.platform-adapter-descriptor-verify.v1`` carrying the descriptor
    digest and primitive totals. The descriptor itself is not persisted
    or activated.
    """
    capsule = _verify_capsule()
    manifest = _load_manifest()
    descriptor = _build_descriptor(manifest)
    _validate_descriptor_against_spec(descriptor, manifest)

    # Defensive cross-check against the settled registry: the descriptor's
    # operation IDs (in order) and per-operation capability states must
    # match the registry. The registry data is canonical JSON already
    # validated by the P1a loader pattern.
    registry = _load_registry()
    reg_ops = registry.get("operations")
    if not isinstance(reg_ops, list):
        raise DescriptorError("registry operations missing")
    reg_ids = [op.get("id") for op in reg_ops]
    if reg_ids != list(_OPERATION_IDS):
        raise DescriptorError(
            f"registry operations ids/order mismatch: {reg_ids}"
        )
    reg_caps = registry.get("capabilities")
    if not isinstance(reg_caps, dict):
        raise DescriptorError("registry capabilities missing")
    for op in _OPERATIONS:
        reg_state = reg_caps.get(op["id"])
        if reg_state != op["capability_state"]:
            raise DescriptorError(
                f"registry capability_state mismatch for {op['id']}: "
                f"registry={reg_state!r} descriptor={op['capability_state']!r}"
            )

    descriptor_bytes = _canonical_json_bytes(descriptor)
    digest = _sha256_bytes(descriptor_bytes)
    primitive_total = sum(
        len(op["legacy_primitives"]) for op in descriptor["operations"]
    )
    return {
        "ok": True,
        "kind": KIND_VERIFY,
        "schema_version": SCHEMA_VERSION,
        "platform_id": PLATFORM_ID,
        "profile_id": PROFILE_ID,
        "activation_state": ACTIVATION_STATE,
        "executable": False,
        "descriptor_digest": digest,
        "operations_total": len(descriptor["operations"]),
        "legacy_primitives_total": primitive_total,
        "capsule": capsule,
    }


# ---------------------------------------------------------------------------
# CLI (one canonical JSON object; no traceback; no override flags).
# ---------------------------------------------------------------------------


class _JSONArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that raises DescriptorError instead of exiting."""

    def error(self, message: str) -> None:  # type: ignore[override]
        raise DescriptorError(f"cli: {message}")


def _emit(stream, payload: dict[str, Any]) -> None:
    stream.write(_canonical_json_bytes(payload).decode("utf-8"))
    stream.flush()


def _build_parser() -> _JSONArgumentParser:
    parser = _JSONArgumentParser(
        prog=SCRIPT_NAME,
        description="ICP P2c Flutter platform-adapter descriptor (non-executable).",
        add_help=True,
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    sub.add_parser("describe", add_help=True)
    sub.add_parser("verify", add_help=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    raw = sys.argv[1:] if argv is None else list(argv)
    try:
        parser = _build_parser()
        args = parser.parse_args(raw)
        if args.subcommand == "describe":
            descriptor = describe()
            _emit(sys.stdout, descriptor)
            return 0
        if args.subcommand == "verify":
            report = verify_descriptor()
            _emit(sys.stdout, report)
            return 0
        raise DescriptorError(f"cli: unknown subcommand: {args.subcommand!r}")
    except DescriptorError as exc:
        _emit(
            sys.stderr,
            {"ok": False, "code": CODE_DESCRIPTOR, "message": str(exc)},
        )
        return 2
    except Exception as exc:  # noqa: BLE001
        _emit(
            sys.stderr,
            {
                "ok": False,
                "code": CODE_DESCRIPTOR,
                "message": type(exc).__name__,
            },
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
