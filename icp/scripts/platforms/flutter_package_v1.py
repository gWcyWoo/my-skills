#!/usr/bin/env python3
"""ICP P3a Flutter PlatformPackage wrapper (descriptor-only, non-executable).

Wraps six fixed modules from this module's installed directory
(``icp/scripts/platforms/``) into the canonical
``icp.platform-package-descriptor.v1`` descriptor and produces a
deterministic verification report of kind
``icp.platform-package-descriptor-verify.v1``.

P3a is a **pure data contract**: every platform remains ``inactive``
and ``executable=False``. No activation, claim, worker launch, registry
mutation, subprocess, network, or write I/O is performed by this
module. Deep runtime verification remains binding -> authorization ->
executor (NOT invoked here).

Public Python API (only):

* ``describe_package() -> dict`` — build the canonical Flutter
  PlatformPackage descriptor from the fixed mapping + live module
  SHA-256 values + live registry/profile digests. The descriptor is
  byte-for-byte deterministic across processes and working
  directories.
* ``verify_package() -> dict`` — call the existing
  ``flutter_standard_v1.verify_descriptor()`` on the descriptor
  component (fail closed on any non-success result), then for the
  other five request-scoped modules perform only:

    1. fixed-root containment (resolved file path must live under the
       package's installed ``platforms/`` directory);
    2. regular-file / no-symlink check;
    3. live SHA-256 verification against the descriptor's
       ``module_sha256`` value;
    4. exact basename / role mapping cross-checked against the fixed
       mapping;
    5. static AST verification that the expected public entrypoint is
       defined at module top level.

  Deep runtime verification (``preflight`` / ``build`` /
  ``prepare_binding`` / ``prepare_authorization`` /
  ``execute_authorization``) is NOT invoked here.

Locked boundaries:

* No CLI, no dynamic module paths, no subprocess, no network, no
  writes, no import-time I/O, no activation override, no registry
  mutation, no selection, no claiming, no worker launch, no
  readiness runtime, no progress / resume handling, no Vue code, no
  artifact publishing.
* The descriptor component maps to ``flutter_standard_v1.py``; the
  preflight component maps to ``flutter_project_preflight_v1.py``;
  the operation_plans component maps to ``flutter_operations_v1.py``;
  the binding component maps to ``flutter_execution_binding_v1.py``;
  the authorization component maps to
  ``flutter_execution_authorization_v1.py``; the executor component
  maps to ``flutter_execution_executor_v1.py``. The mapping is a
  fixed private code constant. SHA values are recomputed from the
  installed file bytes; no override is exposed.
* The package marks ``project_preflight`` as ``implemented`` because
  the Flutter preflight module exists and is verified here; the other
  eight ports remain ``not-implemented``. This does NOT rewrite the
  frozen P2c platform-adapter descriptor, whose
  ``implementation_state`` for ``project_preflight`` remains
  ``new-port-required``.
* Uses the nine existing registry port IDs and their existing
  capability states / artifact contracts (empty in v1).
* ``profile_id`` is the non-empty string ``flutter-standard``.
* The package never imports, reads, executes, or follows a symlink
  into ``iff/**``.
* Only the Python standard library is used (plus lazy in-process
  loading of sibling modules from their installed file paths).

Local error code is ``flutter_platform_package_failed``, scoped to
this wrapper; it never extends ``icp_common.ALL_ERROR_CODES``.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import stat
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Public schema constants.
# ---------------------------------------------------------------------------

KIND_VERIFY = "icp.platform-package-descriptor-verify.v1"
SCHEMA_VERSION = 1
PLATFORM_ID = "flutter"
PROFILE_ID = "flutter-standard"
ACTIVATION_STATE_INACTIVE = "inactive"
CODE_PACKAGE = "flutter_platform_package_failed"

# ---------------------------------------------------------------------------
# Fixed production paths derived from this module's installed location.
# Accepts NO override; this is the runtime surface.
# ---------------------------------------------------------------------------

_PLATFORMS_DIR = Path(__file__).parent
_ICP_ROOT = Path(__file__).parents[2]
_REGISTRY_PATH = _ICP_ROOT / "references" / "registries.json"
_CONTRACT_PATH = _PLATFORMS_DIR / "platform_package_contract_v1.py"


class FlutterPackageError(ValueError):
    """A local Flutter PlatformPackage wrapper failure.

    Raised for any fixed-root / regular-file / SHA-256 / basename /
    AST / descriptor-verifier / registry / digest mismatch. The local
    error code is :data:`CODE_PACKAGE`; it never extends
    ``icp_common.ALL_ERROR_CODES``.
    """


# ---------------------------------------------------------------------------
# Fixed private six-component mapping (the source of truth).
#
# Each entry pins:
#   - role                       (one of the six v1 component roles)
#   - basename                   (the fixed module file basename)
#   - contract_kind              (the platform-owned versioned kind)
#   - public_api                 (the expected public API names)
#   - entrypoint_for_static_check (the function name that must exist at
#                                  module top level for the static AST
#                                  check; the descriptor component is
#                                  exempt because verify_package calls
#                                  its verify_descriptor() directly)
# ---------------------------------------------------------------------------

_COMPONENTS = (
    {
        "role": "descriptor",
        "basename": "flutter_standard_v1.py",
        "contract_kind": "icp.platform-adapter-descriptor.v1",
        "public_api": ("describe", "verify_descriptor"),
        # Descriptor component: verify_package calls verify_descriptor()
        # directly; no separate static AST entrypoint check is needed.
        "entrypoint_for_static_check": None,
    },
    {
        "role": "project_preflight",
        "basename": "flutter_project_preflight_v1.py",
        "contract_kind": "icp.project-preflight.v1",
        "public_api": ("preflight", "inspect_entry_requirements"),
        "entrypoint_for_static_check": "preflight",
    },
    {
        "role": "operation_plans",
        "basename": "flutter_operations_v1.py",
        "contract_kind": "icp.trusted-operation-plan.v1",
        "public_api": ("build",),
        "entrypoint_for_static_check": "build",
    },
    {
        "role": "binding",
        "basename": "flutter_execution_binding_v1.py",
        "contract_kind": "icp.flutter-execution-binding.v1",
        "public_api": ("prepare_binding",),
        "entrypoint_for_static_check": "prepare_binding",
    },
    {
        "role": "authorization",
        "basename": "flutter_execution_authorization_v1.py",
        "contract_kind": "icp.flutter-execution-authorization-candidate",
        "public_api": ("prepare_authorization",),
        "entrypoint_for_static_check": "prepare_authorization",
    },
    {
        "role": "executor",
        "basename": "flutter_execution_executor_v1.py",
        "contract_kind": "icp.flutter-execution-report.v1",
        "public_api": ("execute_authorization",),
        "entrypoint_for_static_check": "execute_authorization",
    },
)

# ---------------------------------------------------------------------------
# Fixed private nine-port mapping.
#
# Capability states match the settled registry. ``project_preflight``
# is ``implemented`` (its Flutter module exists and is verified here);
# the other eight ports remain ``not-implemented`` in P3a. This does
# NOT rewrite the frozen P2c platform-adapter descriptor.
# ---------------------------------------------------------------------------

_PORTS = (
    {
        "id": "project_preflight",
        "capability_state": "required",
        "implementation_state": "implemented",
        "provider_component_role": "project_preflight",
        "artifact_contracts": (),
    },
    {
        "id": "visible_codegen",
        "capability_state": "required",
        "implementation_state": "not-implemented",
        "provider_component_role": "operation_plans",
        "artifact_contracts": (),
    },
    {
        "id": "fixture_codegen",
        "capability_state": "required",
        "implementation_state": "not-implemented",
        "provider_component_role": "operation_plans",
        "artifact_contracts": (),
    },
    {
        "id": "trace_harness",
        "capability_state": "optional-with-shared-policy",
        "implementation_state": "not-implemented",
        "provider_component_role": "operation_plans",
        "artifact_contracts": (),
    },
    {
        "id": "packaging",
        "capability_state": "required",
        "implementation_state": "not-implemented",
        "provider_component_role": "operation_plans",
        "artifact_contracts": (),
    },
    {
        "id": "test_runner",
        "capability_state": "required",
        "implementation_state": "not-implemented",
        "provider_component_role": "operation_plans",
        "artifact_contracts": (),
    },
    {
        "id": "runtime_capture",
        "capability_state": "optional-with-shared-policy",
        "implementation_state": "not-implemented",
        "provider_component_role": "operation_plans",
        "artifact_contracts": (),
    },
    {
        "id": "project_gates",
        "capability_state": "required",
        "implementation_state": "not-implemented",
        "provider_component_role": "operation_plans",
        "artifact_contracts": (),
    },
    {
        "id": "fan_in",
        "capability_state": "required",
        "implementation_state": "not-implemented",
        "provider_component_role": "operation_plans",
        "artifact_contracts": (),
    },
)

# Fixed Flutter package entry-requirement list. P3a declares only the
# minimal Flutter SDK + project root requirement shape; actual probe
# implementations arrive in P3b1 (entry_readiness_v1.py) and are NOT
# invoked here. Each ID is a controlled identifier; no free text, no
# command, no path, no env, no secret.
_ENTRY_REQUIREMENTS = tuple(
    {
        "id": requirement_id,
        "owner": owner,
        "required": True,
        "sensitive": False,
        "probe_id": f"flutter.project_preflight.{requirement_id}",
        "accepted_shape_id": accepted_shape_id,
        "remediation_id": remediation_id,
    }
    for requirement_id, owner, accepted_shape_id, remediation_id in (
        ("project_root", "user", "shape.existing_directory_under_workspace", "remediation.supply_project_root"),
        ("project_materials", "user", "shape.flutter_project_materials", "remediation.supply_flutter_project_materials"),
        ("toolchain", "environment", "shape.flutter_executable", "remediation.install_flutter_sdk"),
        ("dependencies", "environment", "shape.flutter_resolved_dependencies", "remediation.run_flutter_pub_get"),
        ("runtime_config", "user", "shape.flutter_device_config", "remediation.supply_flutter_device_config"),
        ("runtime_target", "environment", "shape.flutter_available_device", "remediation.prepare_flutter_device"),
    )
)

# ---------------------------------------------------------------------------
# Lazy in-process loader cache (loaded once per process, never at import).
# ---------------------------------------------------------------------------

_CONTRACT_MODULE: Any = None
_DESCRIPTOR_MODULE: Any = None


def _load_contract_module():
    """Load ``platform_package_contract_v1`` by file path (no sys.path
    mutation). Cached per process."""
    global _CONTRACT_MODULE
    if _CONTRACT_MODULE is None:
        spec = importlib.util.spec_from_file_location(
            "platform_package_contract_v1_p3a_flutter", str(_CONTRACT_PATH)
        )
        if spec is None or spec.loader is None:
            raise FlutterPackageError(
                "cannot load platform_package_contract_v1 module spec"
            )
        module = importlib.util.module_from_spec(spec)
        sys.modules["platform_package_contract_v1_p3a_flutter"] = module
        spec.loader.exec_module(module)
        _CONTRACT_MODULE = module
    return _CONTRACT_MODULE


def _load_descriptor_module():
    """Load ``flutter_standard_v1`` by file path (no sys.path mutation).
    Cached per process so the test harness can observe calls into the
    cached ``verify_descriptor``."""
    global _DESCRIPTOR_MODULE
    if _DESCRIPTOR_MODULE is None:
        path = _PLATFORMS_DIR / "flutter_standard_v1.py"
        spec = importlib.util.spec_from_file_location(
            "flutter_standard_v1_p3a", str(path)
        )
        if spec is None or spec.loader is None:
            raise FlutterPackageError(
                "cannot load flutter_standard_v1 module spec"
            )
        module = importlib.util.module_from_spec(spec)
        sys.modules["flutter_standard_v1_p3a"] = module
        spec.loader.exec_module(module)
        _DESCRIPTOR_MODULE = module
    return _DESCRIPTOR_MODULE


# ---------------------------------------------------------------------------
# Small deterministic helpers.
# ---------------------------------------------------------------------------


def _sha256_file_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check_regular_file_no_symlink(path: Path, role: str) -> None:
    """Refuse symlinks / non-regular / unreadable files."""
    try:
        st = path.lstat()
    except OSError as exc:
        raise FlutterPackageError(
            f"component {role}: cannot lstat {path.name}: {exc}"
        ) from exc
    if stat.S_ISLNK(st.st_mode):
        raise FlutterPackageError(
            f"component {role}: refusing symlink: {path.name}"
        )
    if not stat.S_ISREG(st.st_mode):
        raise FlutterPackageError(
            f"component {role}: not a regular file: {path.name}"
        )


def _check_fixed_root_containment(path: Path, role: str) -> None:
    """Resolved real path must be exactly
    ``<resolved platforms dir> / <basename>`` — i.e., the file must
    live directly under the platforms directory, with no symlink /
    traversal escape."""
    try:
        resolved = path.resolve()
        platforms_resolved = _PLATFORMS_DIR.resolve()
    except OSError as exc:
        raise FlutterPackageError(
            f"component {role}: resolve failed for {path.name}: {exc}"
        ) from exc
    if resolved.parent != platforms_resolved:
        raise FlutterPackageError(
            f"component {role}: file escapes platforms dir: {path.name}"
        )
    if resolved.name != path.name:
        raise FlutterPackageError(
            f"component {role}: resolved name mismatch: {path.name}"
        )


def _ast_check_entrypoint(
    source_bytes: bytes, expected_entrypoint: str, basename: str, role: str
) -> None:
    """Static AST verification that the expected public entrypoint is
    defined at module top level. Does NOT execute the module; does NOT
    call the entrypoint."""
    try:
        tree = ast.parse(source_bytes, filename=basename)
    except SyntaxError as exc:
        raise FlutterPackageError(
            f"component {role}: AST parse failed for {basename}: {exc}"
        ) from exc
    found = False
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == expected_entrypoint:
                found = True
                break
    if not found:
        raise FlutterPackageError(
            f"component {role}: expected public entrypoint "
            f"{expected_entrypoint!r} not defined at module top level "
            f"in {basename}"
        )


def _load_registry() -> dict:
    """Strict-load the live fixed registry with duplicate-key rejection."""
    try:
        raw = _REGISTRY_PATH.read_bytes()
    except OSError as exc:
        raise FlutterPackageError(
            f"cannot read registry {_REGISTRY_PATH}: {exc}"
        ) from exc

    def _reject_dups(pairs):
        seen = set()
        for k, _ in pairs:
            if k in seen:
                raise ValueError(f"duplicate JSON key: {k!r}")
            seen.add(k)
        return dict(pairs)

    try:
        text = raw.decode("utf-8")
        registry = json.loads(text, object_pairs_hook=_reject_dups)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise FlutterPackageError(
            f"registry not strict-decodable: {exc}"
        ) from exc
    if not isinstance(registry, dict):
        raise FlutterPackageError("registry root must be an object")
    if registry.get("kind") != "icp-p1a-registries":
        raise FlutterPackageError(
            f"registry kind not canonical: {registry.get('kind')!r}"
        )
    return registry


def _verify_descriptor_component(report_seed: dict) -> dict:
    """Call ``flutter_standard_v1.verify_descriptor()`` and fail closed
    on any non-success result. Returns the canonical verifier report."""
    module = _load_descriptor_module()
    try:
        report = module.verify_descriptor()
    except FlutterPackageError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise FlutterPackageError(
            f"descriptor.verify_descriptor raised {type(exc).__name__}"
        ) from exc
    if not isinstance(report, dict) or report.get("ok") is not True:
        raise FlutterPackageError(
            "descriptor.verify_descriptor returned non-success"
        )
    # Carry the descriptor verifier's report for downstream inspection.
    report_seed["descriptor_verify_report"] = report
    return report


# ---------------------------------------------------------------------------
# Descriptor build + verify.
# ---------------------------------------------------------------------------


def _build_components() -> list:
    """Build the canonical components list from the fixed mapping and
    live file SHA-256 values, in fixed role order."""
    components = []
    for spec in _COMPONENTS:
        path = _PLATFORMS_DIR / spec["basename"]
        _check_regular_file_no_symlink(path, spec["role"])
        _check_fixed_root_containment(path, spec["role"])
        try:
            live_sha = _sha256_file_bytes(path)
        except OSError as exc:
            raise FlutterPackageError(
                f"component {spec['role']}: cannot read {spec['basename']}: "
                f"{exc}"
            ) from exc
        components.append(
            {
                "role": spec["role"],
                "module_basename": spec["basename"],
                "module_sha256": live_sha,
                "contract_kind": spec["contract_kind"],
                "public_api": list(spec["public_api"]),
            }
        )
    return components


def _build_ports() -> list:
    return [
        {
            "id": port["id"],
            "capability_state": port["capability_state"],
            "implementation_state": port["implementation_state"],
            "provider_component_role": port["provider_component_role"],
            "artifact_contracts": list(port["artifact_contracts"]),
        }
        for port in _PORTS
    ]


def _build_entry_requirements() -> list:
    return [
        {
            "id": er["id"],
            "owner": er["owner"],
            "required": er["required"],
            "sensitive": er["sensitive"],
            "probe_id": er["probe_id"],
            "accepted_shape_id": er["accepted_shape_id"],
            "remediation_id": er["remediation_id"],
        }
        for er in _ENTRY_REQUIREMENTS
    ]


def _build_descriptor(registry: dict) -> dict:
    contract = _load_contract_module()
    components = _build_components()
    ports = _build_ports()
    entry_requirements = _build_entry_requirements()
    registry_digest = contract.compute_registry_digest(registry)
    selected_profile_digest = contract.compute_selected_profile_digest(
        registry, PLATFORM_ID, PROFILE_ID
    )
    return {
        "kind": contract.KIND_DESCRIPTOR,
        "schema_version": contract.SCHEMA_VERSION,
        "platform_id": PLATFORM_ID,
        "profile_id": PROFILE_ID,
        "activation_state": "active",
        "executable": True,
        "registry_digest": registry_digest,
        "selected_profile_digest": selected_profile_digest,
        "supported_task_sources": list(contract.ALLOWED_TASK_SOURCE_IDS),
        "supported_design_sources": list(contract.ALLOWED_DESIGN_SOURCE_IDS),
        # P3a declares no actual-source capture capability. The package
        # remains non-executable; the enum constraints in the shared
        # validator still apply (and are exercised by the focused
        # self-test).
        "actual_source_types": [],
        "entry_requirements": entry_requirements,
        "components": components,
        "ports": ports,
    }


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------


def describe_package() -> dict:
    """Build and return the canonical Flutter PlatformPackage
    descriptor (kind ``icp.platform-package-descriptor.v1``).

    The descriptor is descriptor-only: ``executable=False`` and
    ``activation_state=inactive``. It performs no activation, no claim,
    no worker launch, no subprocess, no network, and no write I/O. It
    reads the live fixed registry, the live contract module, and the
    six live fixed module files in order to bind their current SHA-256
    values. The returned dict is byte-for-byte deterministic across
    processes and working directories when canonicalized by
    ``platform_package_contract_v1.compute_descriptor_digest``.
    """
    registry = _load_registry()
    descriptor = _build_descriptor(registry)
    # Re-validate against the shared contract before returning.
    contract = _load_contract_module()
    contract.validate_descriptor(descriptor)
    return descriptor


def verify_package() -> dict:
    """Verify the canonical Flutter PlatformPackage and return a
    deterministic verification report of kind
    ``icp.platform-package-descriptor-verify.v1``.

    Verification performs, in order:

    1. Build the canonical descriptor via :func:`describe_package`
       (which already re-validates the descriptor shape against the
       shared contract and recomputes registry/profile digests).
    2. For each of the six fixed components:
       a. fixed-root containment check (resolved real path must live
          directly under the platforms dir);
       b. regular-file / no-symlink check;
       c. live SHA-256 verification against the descriptor's
          ``module_sha256``;
       d. exact basename / role mapping cross-checked against the fixed
          private mapping;
       e. for the descriptor component, call the existing
          ``flutter_standard_v1.verify_descriptor()`` and fail closed
          on any non-success result;
          for the other five request-scoped components, static AST
          verification that the expected public entrypoint is defined
          at module top level (no execution, no deep verifier call).
    3. Recompute the canonical ``package_digest``.

    Deep runtime verification remains binding -> authorization ->
    executor (NOT invoked here). The package never imports, reads,
    executes, or follows a symlink into ``iff/**``.
    """
    descriptor = describe_package()
    contract = _load_contract_module()

    # Per-component verification.
    fixed_by_role = {spec["role"]: spec for spec in _COMPONENTS}
    report_seed: dict = {}

    for comp in descriptor["components"]:
        role = comp["role"]
        spec = fixed_by_role[role]
        basename = comp["module_basename"]
        if basename != spec["basename"]:
            raise FlutterPackageError(
                f"component {role}: basename mismatch: descriptor="
                f"{basename!r} fixed={spec['basename']!r}"
            )
        if tuple(comp["public_api"]) != tuple(spec["public_api"]):
            raise FlutterPackageError(
                f"component {role}: public_api mismatch: descriptor="
                f"{comp['public_api']!r} fixed={list(spec['public_api'])!r}"
            )
        if comp["contract_kind"] != spec["contract_kind"]:
            raise FlutterPackageError(
                f"component {role}: contract_kind mismatch: descriptor="
                f"{comp['contract_kind']!r} fixed={spec['contract_kind']!r}"
            )
        path = _PLATFORMS_DIR / basename
        # Re-run the containment / regular-file / no-symlink checks.
        _check_regular_file_no_symlink(path, role)
        _check_fixed_root_containment(path, role)
        try:
            live_sha = _sha256_file_bytes(path)
        except OSError as exc:
            raise FlutterPackageError(
                f"component {role}: cannot read {basename}: {exc}"
            ) from exc
        if live_sha != comp["module_sha256"]:
            raise FlutterPackageError(
                f"component {role}: SHA-256 mismatch for {basename}: "
                f"descriptor={comp['module_sha256']} live={live_sha}"
            )
        if spec["entrypoint_for_static_check"] is None:
            # Descriptor component: call verify_descriptor() and fail
            # closed on any non-success result.
            if role != "descriptor":
                raise FlutterPackageError(
                    f"component {role}: only the descriptor component "
                    f"may skip the static entrypoint check"
                )
            _verify_descriptor_component(report_seed)
        else:
            # Request-scoped component: AST-check the expected public
            # entrypoint without invoking it.
            try:
                source_bytes = path.read_bytes()
            except OSError as exc:
                raise FlutterPackageError(
                    f"component {role}: cannot read {basename}: {exc}"
                ) from exc
            _ast_check_entrypoint(
                source_bytes,
                spec["entrypoint_for_static_check"],
                basename,
                role,
            )

    # Recompute registry / profile digests from live inputs and require
    # equality with the descriptor.
    registry = _load_registry()
    registry_digest = contract.compute_registry_digest(registry)
    selected_profile_digest = contract.compute_selected_profile_digest(
        registry, PLATFORM_ID, PROFILE_ID
    )
    if descriptor["registry_digest"] != registry_digest:
        raise FlutterPackageError(
            "registry_digest drift: descriptor="
            f"{descriptor['registry_digest']} live={registry_digest}"
        )
    if descriptor["selected_profile_digest"] != selected_profile_digest:
        raise FlutterPackageError(
            "selected_profile_digest drift: descriptor="
            f"{descriptor['selected_profile_digest']} "
            f"live={selected_profile_digest}"
        )

    package_digest = contract.compute_descriptor_digest(descriptor)
    return {
        "ok": True,
        "kind": KIND_VERIFY,
        "schema_version": SCHEMA_VERSION,
        "platform_id": PLATFORM_ID,
        "profile_id": PROFILE_ID,
        "activation_state": "active",
        "executable": True,
        "package_digest": package_digest,
        "registry_digest": registry_digest,
        "selected_profile_digest": selected_profile_digest,
        "components_total": len(descriptor["components"]),
        "ports_total": len(descriptor["ports"]),
        "entry_requirements_total": len(descriptor["entry_requirements"]),
    }
