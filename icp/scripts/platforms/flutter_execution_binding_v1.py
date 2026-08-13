#!/usr/bin/env python3
"""ICP P2e1 Flutter non-executable execution binding.

This module is the **non-executable** deterministic execution binding
for the Flutter ``flutter-standard`` profile. It re-attests the current
frozen selection manifest, vendored capsule, Flutter descriptor, project
preflight, exact operation request, rebuilt plan, and source digests,
then emits a deterministic ``icp.flutter-execution-binding.v1``
document. ``verify_binding()`` re-runs the complete preparation chain
and requires exact equality with the candidate binding.

The slice is **non-executable**:

* no operation plan is executed (the plan is built and verified only);
* the descriptor stays ``inactive`` and the binding ``executable`` is
  always ``False``;
* the module never imports ``subprocess`` (the only subprocess in the
  chain is the fixed ``flutter_project_preflight_v1.preflight()``
  ``flutter --version --machine`` probe, which owns its own read-only
  subprocess surface inside the preflight module);
* no writes, no CLI, no shell, no env overlay, no executable override,
  no registry/path override, no arbitrary argv.

Public Python API (no CLI):

* ``prepare_binding(manifest_path, operation_id, request) -> dict``
* ``verify_binding(binding) -> dict``

Only these two functions plus the module-local typed exception
:class:`FlutterExecutionBindingError` may be public.

Locked boundaries:

* Stdlib only (no ``subprocess`` import). The only subprocess call in
  the chain is the existing fixed
  ``flutter_project_preflight_v1.preflight()`` call, which owns its
  exact read-only ``flutter --version --machine`` probe.
* No plan execution, writes, CLI, shell, env overlay, executable
  override, registry/path override, or arbitrary argv.
* Production code derives the ICP root, scripts dir, capsule path,
  manifest path, descriptor path, preflight path, operations path, and
  verifier path only from this module's installed file location. No
  public override is exposed.
* The binding never imports, reads, executes, or follows a symlink
  into sibling ``iff/``.
* When the operation request has ``run_root``, it must equal the frozen
  manifest ``run_root`` exactly. When it has absolute ``spec_root``, it
  must equal or be a strict no-symlink descendant of the frozen Flutter
  ``state_root``.
* The embedded request, plan, and reports are detached canonical-data
  copies, never the caller's mutable object.
* A fully coordinated unsigned rewrite of an entire binding to another
  valid current run remains outside static authentication; the trusted
  orchestrator must retain the expected selection-manifest path/digest
  out of band. P2e2/orchestrator must compare the binding's
  ``selection_manifest_sha256`` against the expected value before
  executing any plan.
"""

from __future__ import annotations

import copy
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
KIND_BINDING = "icp.flutter-execution-binding.v1"
KIND_VERIFY = "icp.flutter-execution-binding-verify.v1"
PLATFORM_ID = "flutter"
PROFILE_ID = "flutter-standard"
ACTIVATION_STATE = "inactive"

# Local error code (does not extend icp_common.ALL_ERROR_CODES).
CODE = "flutter_execution_binding_failed"

# ---------------------------------------------------------------------------
# Fixed production paths derived from this module's installed location.
# Accepts NO override; this is the runtime surface.
# ---------------------------------------------------------------------------

_ICP_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = Path(__file__).resolve().parents[1]
_PLATFORMS_DIR = Path(__file__).resolve().parent
_VERIFY_SELECTION_PATH = _SCRIPTS_DIR / "verify_selection_manifest_v1.py"
_PREFLIGHT_PATH = _PLATFORMS_DIR / "flutter_project_preflight_v1.py"
_DESCRIPTOR_PATH = _PLATFORMS_DIR / "flutter_standard_v1.py"
_OPERATIONS_PATH = _PLATFORMS_DIR / "flutter_operations_v1.py"
_CAPSULE_MANIFEST_PATH = (
    _ICP_ROOT / "references" / "baselines" / "iff-v1-vendor.json"
)

# The fixed current Flutter state-root directory name. The frozen
# manifest's state_root is ``<project>/.iff`` for Flutter.
_FLUTTER_STATE_DIRNAME = ".iff"


class FlutterExecutionBindingError(Exception):
    """A local Flutter execution binding failure.

    Raised for any selection/capsule/descriptor/preflight/plan/request
    mismatch. Generic failures are converted at the public API boundary
    to instances of this class whose message exposes the original
    exception's type name only; arbitrary exception text is never leaked.
    """


# ---------------------------------------------------------------------------
# Fixed private operation-id -> descriptor port mapping.
#
# Maps each of the eight current trusted-operation plan IDs to exactly
# one descriptor port id, and pins the expected capability state. Both
# tables are fixed code constants that match the settled registry and
# the P2c descriptor; the binding cross-checks them against the current
# descriptor at prepare time.
# ---------------------------------------------------------------------------

_OPERATION_PORT_MAP: dict[str, str] = {
    "flutter.visible_codegen.v1": "visible_codegen",
    "flutter.fixture_codegen.v1": "fixture_codegen",
    "flutter.trace_harness.v1": "trace_harness",
    "flutter.packaging.v1": "packaging",
    "flutter.test_runner.v1": "test_runner",
    "flutter.runtime_capture.v1": "runtime_capture",
    "flutter.project_gates.v1": "project_gates",
    "flutter.fan_in.v1": "fan_in",
}

_OPERATION_CAPABILITY_MAP: dict[str, str] = {
    "flutter.visible_codegen.v1": "required",
    "flutter.fixture_codegen.v1": "required",
    "flutter.trace_harness.v1": "optional-with-shared-policy",
    "flutter.packaging.v1": "required",
    "flutter.test_runner.v1": "required",
    "flutter.runtime_capture.v1": "optional-with-shared-policy",
    "flutter.project_gates.v1": "required",
    "flutter.fan_in.v1": "required",
}

# Exact top-level binding key set (frozen contract).
_BINDING_KEYS = frozenset(
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
        "selection_verification",
        "request",
        "request_digest",
        "plan",
        "plan_digest",
        "preflight",
        "preflight_digest",
        "descriptor_digest",
        "operations_module_sha256",
        "capsule_manifest_sha256",
    }
)

# Exact verify-report key set.
_VERIFY_KEYS = frozenset(
    {
        "ok",
        "kind",
        "schema_version",
        "operation_id",
        "port_id",
        "binding_digest",
        "plan_digest",
        "selection_manifest_sha256",
    }
)

# Digest-bearing fields that must be 64-char lower-hex SHA-256.
_BINDING_DIGEST_FIELDS = (
    "selection_manifest_sha256",
    "request_digest",
    "plan_digest",
    "preflight_digest",
    "descriptor_digest",
    "operations_module_sha256",
    "capsule_manifest_sha256",
)


# ---------------------------------------------------------------------------
# Lazy module loaders (no sys.path mutation, no package import).
# ---------------------------------------------------------------------------

_SELECTION_VERIFY_MODULE: Any = None
_PREFLIGHT_MODULE: Any = None
_DESCRIPTOR_MODULE: Any = None
_OPERATIONS_MODULE: Any = None


def _load_module_by_path(name: str, path: Path):
    """Load ``path`` as a module under ``name`` without touching sys.path."""
    try:
        if path.is_symlink():
            raise FlutterExecutionBindingError(f"refusing symlink module: {path}")
        st = path.lstat()
    except OSError as exc:
        raise FlutterExecutionBindingError(
            f"cannot lstat module {path}: {type(exc).__name__}"
        ) from exc
    if not stat.S_ISREG(st.st_mode):
        raise FlutterExecutionBindingError(f"module not a regular file: {path}")
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise FlutterExecutionBindingError(f"cannot load module spec: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_selection_verify_module():
    """Load the shared selection-manifest verifier module (test seam)."""
    global _SELECTION_VERIFY_MODULE
    if _SELECTION_VERIFY_MODULE is None:
        _SELECTION_VERIFY_MODULE = _load_module_by_path(
            "verify_selection_manifest_v1_p2e1_binding", _VERIFY_SELECTION_PATH
        )
    return _SELECTION_VERIFY_MODULE


def _load_preflight_module():
    """Load the fixed Flutter project preflight module (test seam)."""
    global _PREFLIGHT_MODULE
    if _PREFLIGHT_MODULE is None:
        _PREFLIGHT_MODULE = _load_module_by_path(
            "flutter_project_preflight_v1_p2e1_binding", _PREFLIGHT_PATH
        )
    return _PREFLIGHT_MODULE


def _load_descriptor_module():
    """Load the fixed Flutter descriptor module (test seam)."""
    global _DESCRIPTOR_MODULE
    if _DESCRIPTOR_MODULE is None:
        _DESCRIPTOR_MODULE = _load_module_by_path(
            "flutter_standard_v1_p2e1_binding", _DESCRIPTOR_PATH
        )
    return _DESCRIPTOR_MODULE


def _load_operations_module():
    """Load the fixed Flutter operations plan registry module (test seam)."""
    global _OPERATIONS_MODULE
    if _OPERATIONS_MODULE is None:
        _OPERATIONS_MODULE = _load_module_by_path(
            "flutter_operations_v1_p2e1_binding", _OPERATIONS_PATH
        )
    return _OPERATIONS_MODULE


# ---------------------------------------------------------------------------
# Canonical JSON / digest helpers.
# ---------------------------------------------------------------------------


def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise FlutterExecutionBindingError(
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
# Request validation helpers.
# ---------------------------------------------------------------------------


def _is_canonical_json_suitable(value: Any) -> bool:
    """True iff ``value`` round-trips through canonical JSON without loss.

    Walks the structure recursively and rejects any non-JSON type
    (tuple, set, bytes, complex, custom object, NaN/Infinity floats)."""
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        # Reject NaN / Infinity (json.dumps would emit NaN tokens by
        # default, breaking canonical round-tripping).
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


def _validate_root_path(value: Any, role: str) -> Path:
    """Validate an absolute, lexically normalized, non-symlink real
    directory. Returns the resolved :class:`Path`."""
    if not isinstance(value, str):
        raise FlutterExecutionBindingError(
            f"{role}: must be a string, got {type(value).__name__}"
        )
    raw = Path(value)
    if not raw.is_absolute():
        raise FlutterExecutionBindingError(f"{role}: not absolute: {value!r}")
    if any(part == ".." for part in raw.parts):
        raise FlutterExecutionBindingError(f"{role}: contains '..': {value!r}")
    if os.path.normpath(value) != value:
        raise FlutterExecutionBindingError(
            f"{role}: not lexically normalized: {value!r}"
        )
    try:
        resolved = raw.resolve(strict=True)
    except FileNotFoundError as exc:
        raise FlutterExecutionBindingError(
            f"{role}: does not exist: {value!r}"
        ) from exc
    except RuntimeError as exc:
        raise FlutterExecutionBindingError(
            f"{role}: resolve loop: {type(exc).__name__}"
        ) from exc
    except OSError as exc:
        raise FlutterExecutionBindingError(
            f"{role}: resolve failed: {type(exc).__name__}"
        ) from exc
    if resolved != raw:
        raise FlutterExecutionBindingError(
            f"{role}: supplied path differs from strict resolve "
            f"(symlinked root or ancestor)"
        )
    try:
        if resolved.is_symlink():
            raise FlutterExecutionBindingError(f"{role}: refusing symlink: {resolved}")
        st = resolved.stat()
    except OSError as exc:
        raise FlutterExecutionBindingError(
            f"{role}: cannot stat: {type(exc).__name__}"
        ) from exc
    if not stat.S_ISDIR(st.st_mode):
        raise FlutterExecutionBindingError(f"{role}: not a directory: {resolved}")
    return resolved


def _is_strictly_inside_no_symlink(child: Path, parent: Path) -> bool:
    """True if ``child`` is a strict descendant of ``parent`` with no
    symlinked component between them. Both paths must already be
    canonical real paths."""
    if child == parent:
        return False
    try:
        rel = child.relative_to(parent)
    except ValueError:
        return False
    # Walk each intermediate component and require it to be a non-symlink
    # directory. ``child`` and ``parent`` are already canonical so the
    # leaf/intermediate resolve is stable; this re-walks defensively.
    current = parent
    for part in rel.parts:
        current = current / part
        try:
            if current.is_symlink():
                return False
        except OSError:
            return False
    return True


# ---------------------------------------------------------------------------
# prepare_binding implementation.
# ---------------------------------------------------------------------------


def _prepare_binding_impl(
    manifest_path: str | os.PathLike[str],
    operation_id: str,
    request: dict[str, Any],
) -> dict[str, Any]:
    # 1. Selection verification (re-attests current registry/profile/
    #    rules/runtime-script digests and canonical bytes).
    sel_verify = _load_selection_verify_module()
    selection = sel_verify.verify(manifest_path)

    # 2. Frozen platform/profile must be exactly flutter/flutter-standard.
    if selection["platform_id"] != PLATFORM_ID:
        raise FlutterExecutionBindingError(
            f"selection platform_id must be {PLATFORM_ID!r}, "
            f"got {selection['platform_id']!r}"
        )
    if selection["profile_id"] != PROFILE_ID:
        raise FlutterExecutionBindingError(
            f"selection profile_id must be {PROFILE_ID!r}, "
            f"got {selection['profile_id']!r}"
        )

    frozen_project_root = Path(selection["project_root"])
    frozen_state_root = Path(selection["state_root"])
    frozen_run_root = Path(selection["run_root"])

    # 3. Verify the current vendored capsule + Flutter descriptor through
    #    their fixed installed APIs.
    desc_module = _load_descriptor_module()
    descriptor_report = desc_module.verify_descriptor()

    # 4. Descriptor must remain inactive/non-executable; operation_id
    #    must be one of the current eight plan IDs.
    if descriptor_report["activation_state"] != ACTIVATION_STATE:
        raise FlutterExecutionBindingError(
            f"descriptor activation_state must be {ACTIVATION_STATE!r}, "
            f"got {descriptor_report['activation_state']!r}"
        )
    if descriptor_report["executable"] is not False:
        raise FlutterExecutionBindingError(
            "descriptor executable must be false"
        )
    if not isinstance(operation_id, str):
        raise FlutterExecutionBindingError(
            f"operation_id must be a string, got {type(operation_id).__name__}"
        )
    if operation_id not in _OPERATION_PORT_MAP:
        raise FlutterExecutionBindingError(
            f"unknown operation_id: {operation_id!r}"
        )
    port_id = _OPERATION_PORT_MAP[operation_id]
    capability_state = _OPERATION_CAPABILITY_MAP[operation_id]

    # Cross-check the capability state against the current descriptor.
    descriptor = desc_module.describe()
    desc_ops = {op["id"]: op for op in descriptor["operations"]}
    if port_id not in desc_ops:
        raise FlutterExecutionBindingError(
            f"port {port_id!r} not in current descriptor"
        )
    desc_cap = desc_ops[port_id]["capability_state"]
    # 5. Frozen capability state and descriptor capability state must
    #    match and must not be ``unsupported``.
    if desc_cap != capability_state:
        raise FlutterExecutionBindingError(
            f"capability_state mismatch for {operation_id!r}: "
            f"frozen={capability_state!r} descriptor={desc_cap!r}"
        )
    if capability_state == "unsupported":
        raise FlutterExecutionBindingError(
            f"capability_state for {operation_id!r} is unsupported"
        )

    # 6. Request validation.
    if not isinstance(request, dict):
        raise FlutterExecutionBindingError(
            f"request must be a dict, got {type(request).__name__}"
        )
    if not _is_canonical_json_suitable(request):
        raise FlutterExecutionBindingError(
            "request is not canonical-JSON suitable"
        )
    if "project_root" not in request:
        raise FlutterExecutionBindingError("request must contain project_root")
    req_project_root = _validate_root_path(
        request["project_root"], "request.project_root"
    )
    if req_project_root != frozen_project_root:
        raise FlutterExecutionBindingError(
            f"request.project_root must equal frozen manifest "
            f"project_root: {req_project_root} != {frozen_project_root}"
        )
    # When the request carries run_root it must equal the frozen
    # manifest run_root exactly.
    if "run_root" in request:
        req_run_root = _validate_root_path(
            request["run_root"], "request.run_root"
        )
        if req_run_root != frozen_run_root:
            raise FlutterExecutionBindingError(
                f"request.run_root must equal frozen manifest run_root: "
                f"{req_run_root} != {frozen_run_root}"
            )
    # When the request carries an absolute spec_root it must equal or be
    # a strict no-symlink descendant of the frozen Flutter state_root.
    if "spec_root" in request and isinstance(request["spec_root"], str):
        req_spec_root = _validate_root_path(
            request["spec_root"], "request.spec_root"
        )
        if req_spec_root == frozen_state_root:
            pass  # equal is allowed
        elif not _is_strictly_inside_no_symlink(req_spec_root, frozen_state_root):
            raise FlutterExecutionBindingError(
                f"request.spec_root must equal or be a strict no-symlink "
                f"descendant of frozen state_root {frozen_state_root}, "
                f"got {req_spec_root}"
            )

    # 7. Fresh fixed Flutter project preflight on the frozen project root.
    preflight_module = _load_preflight_module()
    preflight_report = preflight_module.preflight(str(frozen_project_root))
    if preflight_report["platform_id"] != PLATFORM_ID:
        raise FlutterExecutionBindingError(
            f"preflight platform_id must be {PLATFORM_ID!r}"
        )
    if preflight_report["profile_id"] != PROFILE_ID:
        raise FlutterExecutionBindingError(
            f"preflight profile_id must be {PROFILE_ID!r}"
        )
    if Path(preflight_report["project_root"]) != frozen_project_root:
        raise FlutterExecutionBindingError(
            f"preflight project_root must equal frozen project_root"
        )

    # 8. Build the plan internally and verify it. Never accept a
    #    caller-supplied plan.
    op_module = _load_operations_module()
    plan = op_module.build(operation_id, copy.deepcopy(request))
    plan_verify = op_module.verify_plan(plan)

    # 9. Compute digests and assemble the deterministic binding.
    manifest_sha = selection["manifest_sha256"]
    request_digest = plan["request_digest"]
    plan_digest = plan_verify["plan_digest"]
    preflight_digest = _sha256_bytes(
        _canonical_json_bytes(preflight_report)
    )
    descriptor_digest = descriptor_report["descriptor_digest"]
    operations_module_sha = _sha256_file(_OPERATIONS_PATH)
    capsule_manifest_sha = _sha256_file(_CAPSULE_MANIFEST_PATH)

    binding: dict[str, Any] = {
        "kind": KIND_BINDING,
        "schema_version": SCHEMA_VERSION,
        "platform_id": PLATFORM_ID,
        "profile_id": PROFILE_ID,
        "activation_state": ACTIVATION_STATE,
        "executable": False,
        "operation_id": operation_id,
        "port_id": port_id,
        "capability_state": capability_state,
        "selection_manifest_path": selection["manifest_path"],
        "selection_manifest_sha256": manifest_sha,
        "selection_verification": copy.deepcopy(selection),
        "request": copy.deepcopy(request),
        "request_digest": request_digest,
        "plan": copy.deepcopy(plan),
        "plan_digest": plan_digest,
        "preflight": copy.deepcopy(preflight_report),
        "preflight_digest": preflight_digest,
        "descriptor_digest": descriptor_digest,
        "operations_module_sha256": operations_module_sha,
        "capsule_manifest_sha256": capsule_manifest_sha,
    }
    return binding


def prepare_binding(
    manifest_path: str | os.PathLike[str],
    operation_id: str,
    request: dict[str, Any],
) -> dict[str, Any]:
    """Prepare a deterministic ``icp.flutter-execution-binding.v1``
    binding for ``operation_id`` against the frozen selection manifest
    at ``manifest_path``.

    Re-attests the current selection manifest, vendored capsule, Flutter
    descriptor, project preflight, exact operation request, rebuilt
    plan, and source digests. The binding is non-executable: no plan is
    executed, ``executable`` is always ``False``, and
    ``activation_state`` is always ``inactive``.

    Raises :class:`FlutterExecutionBindingError` on any failure; generic
    exceptions are wrapped to type-only messages.
    """
    try:
        return _prepare_binding_impl(manifest_path, operation_id, request)
    except FlutterExecutionBindingError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise FlutterExecutionBindingError(
            f"prepare_binding raised {type(exc).__name__}"
        ) from exc


# ---------------------------------------------------------------------------
# verify_binding implementation.
# ---------------------------------------------------------------------------


def _require_bool(value: Any, role: str) -> bool:
    if value is True or value is False:
        return value
    raise FlutterExecutionBindingError(
        f"{role}: must be a bool, got {type(value).__name__}"
    )


def _require_int(value: Any, role: str) -> int:
    if isinstance(value, bool):
        raise FlutterExecutionBindingError(
            f"{role}: must be an int, got bool"
        )
    if not isinstance(value, int):
        raise FlutterExecutionBindingError(
            f"{role}: must be an int, got {type(value).__name__}"
        )
    return value


def _require_str(value: Any, role: str) -> str:
    if not isinstance(value, str):
        raise FlutterExecutionBindingError(
            f"{role}: must be a string, got {type(value).__name__}"
        )
    return value


def _require_dict(value: Any, role: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FlutterExecutionBindingError(
            f"{role}: must be an object, got {type(value).__name__}"
        )
    return value


def _validate_candidate_shape(binding: dict[str, Any]) -> None:
    """Minimum safe type / literal / digest checks before re-running the
    preparation chain."""
    keys = set(binding.keys())
    if keys != _BINDING_KEYS:
        extra = sorted(keys - _BINDING_KEYS)
        missing = sorted(_BINDING_KEYS - keys)
        raise FlutterExecutionBindingError(
            f"binding keys mismatch: extra={extra} missing={missing}"
        )
    if binding["kind"] != KIND_BINDING:
        raise FlutterExecutionBindingError(
            f"binding kind mismatch: {binding['kind']!r}"
        )
    if _require_int(binding["schema_version"], "schema_version") != SCHEMA_VERSION:
        raise FlutterExecutionBindingError(
            f"binding schema_version mismatch: {binding['schema_version']!r}"
        )
    if binding["platform_id"] != PLATFORM_ID:
        raise FlutterExecutionBindingError(
            f"binding platform_id mismatch: {binding['platform_id']!r}"
        )
    if binding["profile_id"] != PROFILE_ID:
        raise FlutterExecutionBindingError(
            f"binding profile_id mismatch: {binding['profile_id']!r}"
        )
    if binding["activation_state"] != ACTIVATION_STATE:
        raise FlutterExecutionBindingError(
            f"binding activation_state mismatch: "
            f"{binding['activation_state']!r}"
        )
    # executable must be exactly False (bool), not 0/1.
    if _require_bool(binding["executable"], "executable") is not False:
        raise FlutterExecutionBindingError(
            "binding executable must be false"
        )
    _require_str(binding["operation_id"], "operation_id")
    _require_str(binding["port_id"], "port_id")
    _require_str(binding["capability_state"], "capability_state")
    _require_str(binding["selection_manifest_path"], "selection_manifest_path")
    _require_dict(binding["selection_verification"], "selection_verification")
    _require_dict(binding["request"], "request")
    _require_dict(binding["plan"], "plan")
    _require_dict(binding["preflight"], "preflight")
    # Digest fields must be well-formed sha256 hex.
    for field in _BINDING_DIGEST_FIELDS:
        if not _is_sha256_hex(binding[field]):
            raise FlutterExecutionBindingError(
                f"binding {field} malformed: {binding[field]!r}"
            )


def _verify_binding_impl(binding: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(binding, dict):
        raise FlutterExecutionBindingError(
            f"binding must be a dict, got {type(binding).__name__}"
        )
    # Minimum safe type / literal / digest checks first.
    _validate_candidate_shape(binding)

    # Take only selection_manifest_path, operation_id, and detached
    # request from the candidate.
    manifest_path = binding["selection_manifest_path"]
    operation_id = binding["operation_id"]
    request = copy.deepcopy(binding["request"])

    # Re-run the complete current preparation chain.
    rebuilt = _prepare_binding_impl(manifest_path, operation_id, request)

    # Require exact equality with the candidate binding.
    if rebuilt != binding:
        raise FlutterExecutionBindingError(
            "candidate binding does not equal freshly rebuilt binding"
        )

    # Compute the binding digest and return the exact report.
    binding_digest = _sha256_bytes(_canonical_json_bytes(binding))
    return {
        "ok": True,
        "kind": KIND_VERIFY,
        "schema_version": SCHEMA_VERSION,
        "operation_id": operation_id,
        "port_id": binding["port_id"],
        "binding_digest": binding_digest,
        "plan_digest": binding["plan_digest"],
        "selection_manifest_sha256": binding["selection_manifest_sha256"],
    }


def verify_binding(binding: dict[str, Any]) -> dict[str, Any]:
    """Verify a ``icp.flutter-execution-binding.v1`` candidate binding.

    Performs minimum safe type/literal/digest checks, then re-runs the
    complete current preparation chain (selection verification, capsule,
    descriptor, preflight, plan build + verify) using only
    ``selection_manifest_path``, ``operation_id``, and a detached copy
    of ``request`` from the candidate. Requires exact equality between
    the candidate and the freshly rebuilt binding.

    Returns the canonical verify report. Raises
    :class:`FlutterExecutionBindingError` on any failure.
    """
    try:
        return _verify_binding_impl(binding)
    except FlutterExecutionBindingError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise FlutterExecutionBindingError(
            f"verify_binding raised {type(exc).__name__}"
        ) from exc
