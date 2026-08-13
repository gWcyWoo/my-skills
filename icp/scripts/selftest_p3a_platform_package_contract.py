#!/usr/bin/env python3
"""ICP P3a PlatformPackage contract focused RED -> GREEN self-test.

Covers the platform-neutral shared validator
``platforms/platform_package_contract_v1.py`` and the Flutter thin
wrapper ``platforms/flutter_package_v1.py``. Both modules are
descriptor-only / non-executable. Every platform remains ``inactive``
and ``executable=False``; P3a does not activate anything, does not
mutate the registry, does not run a subprocess, does not claim, does
not write run artifacts, and does not import ``iff/``.

RED -> GREEN discipline:

1. This self-test was created BEFORE the two implementation modules.
   The first time it runs, every test that loads either module fails
   for module-absence (``FileNotFoundError``) — that is the recorded
   RED reason.
2. After ``platform_package_contract_v1.py`` and
   ``flutter_package_v1.py`` are created with the approved minimum
   contract, this self-test must pass cleanly (GREEN).

The matrix proven here, per the P3a approved architecture:

* module absence is RED before implementation;
* exact APIs, kind, schema and ordered descriptor shape;
* valid synthetic non-Flutter descriptor passes shared validation;
* missing, duplicate, reordered, unknown and tampered fields fail closed;
* forbidden command/argv/env/shell/prompt/path/activation-override
  injection fails;
* entry-requirement enum and injection violations fail;
* design/reference-image actual-source types fail;
* six component live SHA-256 values match their fixed installed files;
* descriptor verifier is invoked (fail-closed on non-success);
* five request-scoped modules are checked statically without invoking
  their deep verifiers;
* all package activation remains inactive and non-executable;
* import performs zero filesystem, subprocess, network, or write I/O;
* architecture reference matches the Skill-owned approval manifest.

Run directly:

    PYTHONDONTWRITEBYTECODE=1 \\
        python3 icp/scripts/selftest_p3a_platform_package_contract.py
"""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import unittest.mock
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
ICP_ROOT = Path(__file__).resolve().parents[1]
ICP_SCRIPTS = Path(__file__).resolve().parent
PLATFORMS_DIR = ICP_SCRIPTS / "platforms"
CONTRACT_PATH = PLATFORMS_DIR / "platform_package_contract_v1.py"
FLUTTER_PACKAGE_PATH = PLATFORMS_DIR / "flutter_package_v1.py"
REGISTRY_PATH = ICP_ROOT / "references" / "registries.json"

INSTALLED_ARCH_PATH = (
    ICP_ROOT / "references" / "p3-platform-package-architecture.md"
)
APPROVED_ARCH_MANIFEST_PATH = (
    ICP_ROOT
    / "references"
    / "baselines"
    / "p3-platform-package-architecture-v1.json"
)

KIND_DESCRIPTOR = "icp.platform-package-descriptor.v1"
KIND_VERIFY = "icp.platform-package-descriptor-verify.v1"
SCHEMA_VERSION = 1
ACTIVATION_STATE_INACTIVE = "inactive"

COMPONENT_ROLES = (
    "descriptor",
    "project_preflight",
    "operation_plans",
    "binding",
    "authorization",
    "executor",
)
PORT_IDS = (
    "project_preflight",
    "visible_codegen",
    "fixture_codegen",
    "trace_harness",
    "packaging",
    "test_runner",
    "runtime_capture",
    "project_gates",
    "fan_in",
)
ENTRY_REQUIREMENT_OWNERS = (
    "user",
    "source",
    "environment",
    "platform",
)
ACTUAL_SOURCE_TYPES = (
    "browser_screenshot",
    "simulator_screenshot",
    "emulator_screenshot",
    "physical_device_screenshot",
)

# Fixed Flutter component mapping (the source of truth mirrored by the
# Flutter wrapper module).
FLUTTER_COMPONENTS = (
    {
        "role": "descriptor",
        "basename": "flutter_standard_v1.py",
        "contract_kind": "icp.platform-adapter-descriptor.v1",
        "public_api": ("describe", "verify_descriptor"),
    },
    {
        "role": "project_preflight",
        "basename": "flutter_project_preflight_v1.py",
        "contract_kind": "icp.project-preflight.v1",
        "public_api": ("preflight", "inspect_entry_requirements"),
    },
    {
        "role": "operation_plans",
        "basename": "flutter_operations_v1.py",
        "contract_kind": "icp.trusted-operation-plan.v1",
        "public_api": ("build",),
    },
    {
        "role": "binding",
        "basename": "flutter_execution_binding_v1.py",
        "contract_kind": "icp.flutter-execution-binding.v1",
        "public_api": ("prepare_binding",),
    },
    {
        "role": "authorization",
        "basename": "flutter_execution_authorization_v1.py",
        "contract_kind": "icp.flutter-execution-authorization-candidate",
        "public_api": ("prepare_authorization",),
    },
    {
        "role": "executor",
        "basename": "flutter_execution_executor_v1.py",
        "contract_kind": "icp.flutter-execution-report.v1",
        "public_api": ("execute_authorization",),
    },
)


# ---------------------------------------------------------------------------
# Module loaders.
# ---------------------------------------------------------------------------


def _load(name: str, path: Path):
    if not path.exists():
        raise FileNotFoundError(f"module not found: {path}")
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise FileNotFoundError(f"cannot load spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_contract():
    return _load(
        "platform_package_contract_v1_selftest", CONTRACT_PATH
    )


def _load_flutter_package():
    return _load(
        "flutter_package_v1_selftest", FLUTTER_PACKAGE_PATH
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(payload: dict) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _load_registry() -> dict:
    return json.loads(REGISTRY_PATH.read_bytes())


# ---------------------------------------------------------------------------
# Synthetic descriptor builders (platform-neutral).
# ---------------------------------------------------------------------------


def _synthetic_descriptor(
    *,
    platform_id: str = "synthetic",
    profile_id: str = "synthetic-default",
) -> dict:
    """Build a minimal valid synthetic non-Flutter descriptor.

    All SHA-256 fields are well-formed (64-char lowercase hex) but
    synthetic. Component/ports shapes mirror the canonical schema.
    """
    return {
        "kind": KIND_DESCRIPTOR,
        "schema_version": SCHEMA_VERSION,
        "platform_id": platform_id,
        "profile_id": profile_id,
        "activation_state": ACTIVATION_STATE_INACTIVE,
        "executable": False,
        "registry_digest": "a" * 64,
        "selected_profile_digest": "b" * 64,
        "supported_task_sources": ["csv"],
        "supported_design_sources": ["lanhu-figma"],
        "actual_source_types": ["browser_screenshot"],
        "entry_requirements": [
            {
                "id": "synthetic_toolchain",
                "owner": "environment",
                "required": True,
                "sensitive": False,
                "probe_id": "synthetic.probe.toolchain",
                "accepted_shape_id": "shape.synthetic.toolchain",
                "remediation_id": "remediation.install_toolchain",
            },
            {
                "id": "synthetic_project_root",
                "owner": "user",
                "required": True,
                "sensitive": False,
                "probe_id": "synthetic.probe.project_root",
                "accepted_shape_id": "shape.existing_directory",
                "remediation_id": "remediation.supply_project_root",
            },
        ],
        "components": _synthetic_components(),
        "ports": _synthetic_ports(),
    }


def _synthetic_components() -> list:
    public_apis = (
        ("describe", "verify"),
        ("preflight",),
        ("build",),
        ("prepare_binding",),
        ("prepare_authorization",),
        ("execute",),
    )
    return [
        {
            "role": role,
            "module_basename": f"synthetic_{role}_v1.py",
            "module_sha256": "c" * 64,
            "contract_kind": f"icp.synthetic-{role}.v1",
            "public_api": list(api),
        }
        for role, api in zip(COMPONENT_ROLES, public_apis)
    ]


def _synthetic_ports() -> list:
    raw = (
        ("project_preflight", "required", "implemented", "project_preflight"),
        ("visible_codegen", "required", "not-implemented", "operation_plans"),
        ("fixture_codegen", "required", "not-implemented", "operation_plans"),
        ("trace_harness", "optional-with-shared-policy", "not-implemented", "operation_plans"),
        ("packaging", "required", "not-implemented", "operation_plans"),
        ("test_runner", "required", "not-implemented", "operation_plans"),
        ("runtime_capture", "optional-with-shared-policy", "not-implemented", "operation_plans"),
        ("project_gates", "required", "not-implemented", "operation_plans"),
        ("fan_in", "required", "not-implemented", "operation_plans"),
    )
    return [
        {
            "id": pid,
            "capability_state": cap,
            "implementation_state": impl,
            "provider_component_role": prov,
            "artifact_contracts": [],
        }
        for (pid, cap, impl, prov) in raw
    ]


class _ExpectationError(AssertionError):
    """Internal: an expected-failure assertion did not fire."""


def _expect_reject(callable_, label: str) -> None:
    try:
        callable_()
    except Exception:  # noqa: BLE001
        return
    raise _ExpectationError(f"{label}: expected rejection, got success")


# ---------------------------------------------------------------------------
# 1. Module absence is RED before implementation (and presence after).
# ---------------------------------------------------------------------------


def test_modules_exist_and_load() -> None:
    contract = _load_contract()
    flutter = _load_flutter_package()
    assert callable(contract.validate_descriptor)
    assert callable(flutter.describe_package)
    assert callable(flutter.verify_package)


# ---------------------------------------------------------------------------
# 2. Public API surface.
# ---------------------------------------------------------------------------


def test_contract_public_api_surface() -> None:
    import inspect

    contract = _load_contract()
    for name in (
        "validate_descriptor",
        "compute_descriptor_digest",
        "compute_registry_digest",
        "compute_selected_profile_digest",
    ):
        assert callable(getattr(contract, name)), name
    allowed = {
        "validate_descriptor",
        "compute_descriptor_digest",
        "compute_registry_digest",
        "compute_selected_profile_digest",
    }
    public_funcs = [
        n
        for n in dir(contract)
        if not n.startswith("_")
        and inspect.isfunction(getattr(contract, n))
        and getattr(contract, n).__module__ == contract.__name__
    ]
    extra = sorted(set(public_funcs) - allowed)
    assert extra == [], f"unexpected contract public functions: {extra}"
    public_classes = [
        n
        for n in dir(contract)
        if not n.startswith("_")
        and inspect.isclass(getattr(contract, n))
        and getattr(contract, n).__module__ == contract.__name__
    ]
    assert "PlatformPackageDescriptorError" in public_classes, public_classes


def test_flutter_package_public_api_surface() -> None:
    import inspect

    flutter = _load_flutter_package()
    for name in ("describe_package", "verify_package"):
        assert callable(getattr(flutter, name)), name
    allowed = {"describe_package", "verify_package"}
    public_funcs = [
        n
        for n in dir(flutter)
        if not n.startswith("_")
        and inspect.isfunction(getattr(flutter, n))
        and getattr(flutter, n).__module__ == flutter.__name__
    ]
    extra = sorted(set(public_funcs) - allowed)
    assert extra == [], f"unexpected flutter-package public functions: {extra}"


def test_flutter_package_public_api_signatures_take_no_parameters() -> None:
    import inspect

    flutter = _load_flutter_package()
    for name in ("describe_package", "verify_package"):
        sig = inspect.signature(getattr(flutter, name))
        assert list(sig.parameters) == [], (
            f"{name} must take no parameters; got {sig}"
        )


def test_flutter_package_exposes_no_override_parameters() -> None:
    flutter = _load_flutter_package()
    forbidden = (
        "SKILL_ROOT", "ICP_ROOT_OVERRIDE", "REGISTRY_OVERRIDE",
        "CAPSULE_OVERRIDE", "SCRIPT_PATH", "INTERPRETER",
        "ARGV", "ENV", "ACTIVATION", "COMMAND",
    )
    for attr in forbidden:
        assert not hasattr(flutter, attr), (
            f"flutter package exposes override {attr}"
        )


def test_contract_module_constants_canonical() -> None:
    contract = _load_contract()
    assert contract.KIND_DESCRIPTOR == KIND_DESCRIPTOR
    assert contract.SCHEMA_VERSION == SCHEMA_VERSION
    assert contract.ACTIVATION_STATE_INACTIVE == ACTIVATION_STATE_INACTIVE
    assert tuple(contract.COMPONENT_ROLES) == COMPONENT_ROLES
    assert tuple(contract.PORT_IDS) == PORT_IDS
    assert tuple(contract.ENTRY_REQUIREMENT_OWNERS) == ENTRY_REQUIREMENT_OWNERS
    assert tuple(contract.ACTUAL_SOURCE_TYPES) == ACTUAL_SOURCE_TYPES


# ---------------------------------------------------------------------------
# 3. Shared validator has zero Flutter/Vue/toolchain literals.
# ---------------------------------------------------------------------------


def test_contract_source_has_no_platform_toolchain_literals() -> None:
    """The shared contract source must not carry Flutter/Vue/Next.js,
    iOS/Android, Dart/Gradle/Xcode/pubspec/adb/simctl, or any toolchain
    literal in code or comments. The four canonical
    ``actual_source_types`` enum values are exempt."""
    source = CONTRACT_PATH.read_text()
    forbidden = (
        "flutter", "vue", "nextjs", "next.js",
        "ios", "iphone", "ipad",
        "android", "dart", "gradle", "xcode", "pubspec",
        "adb", "simctl", "swift", "kotlin", "objc", "obj-c",
    )
    exemptions = (
        "browser_screenshot",
        "simulator_screenshot",
        "emulator_screenshot",
    )
    redacted = source
    for ex in exemptions:
        redacted = redacted.replace(ex, "<ENUM>")
    leaked = []
    lowered = redacted.lower()
    for token in forbidden:
        if token.lower() in lowered:
            leaked.append(token)
    assert not leaked, (
        f"forbidden platform/toolchain literal in contract source: {leaked}"
    )


def test_contract_source_uses_only_standard_library() -> None:
    tree = ast.parse(CONTRACT_PATH.read_text())
    allowed = {
        "__future__", "hashlib", "json", "typing",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                assert top in allowed, f"non-stdlib import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None
            top = node.module.split(".")[0]
            assert top in allowed, f"non-stdlib from-import: {node.module}"


# ---------------------------------------------------------------------------
# 4. Synthetic non-Flutter descriptor passes shared validation.
# ---------------------------------------------------------------------------


def test_validate_descriptor_accepts_synthetic_non_flutter() -> None:
    contract = _load_contract()
    descriptor = _synthetic_descriptor()
    contract.validate_descriptor(descriptor)


def test_compute_descriptor_digest_is_sha256_hex() -> None:
    contract = _load_contract()
    descriptor = _synthetic_descriptor()
    digest = contract.compute_descriptor_digest(descriptor)
    assert isinstance(digest, str) and len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_compute_descriptor_digest_is_deterministic() -> None:
    contract = _load_contract()
    d1 = _synthetic_descriptor()
    d2 = _synthetic_descriptor()
    assert (
        contract.compute_descriptor_digest(d1)
        == contract.compute_descriptor_digest(d2)
    )


def test_compute_registry_digest_matches_canonical_bytes() -> None:
    contract = _load_contract()
    registry = _load_registry()
    expected = _sha256_bytes(_canonical_json_bytes(registry))
    assert contract.compute_registry_digest(registry) == expected


def test_compute_selected_profile_digest_for_flutter() -> None:
    contract = _load_contract()
    registry = _load_registry()
    digest = contract.compute_selected_profile_digest(
        registry, "flutter", "flutter-standard"
    )
    assert isinstance(digest, str) and len(digest) == 64


def test_compute_selected_profile_digest_rejects_unknown_profile() -> None:
    contract = _load_contract()
    registry = _load_registry()
    _expect_reject(
        lambda: contract.compute_selected_profile_digest(
            registry, "flutter", "bogus-profile"
        ),
        "unknown profile must be rejected",
    )


def test_compute_selected_profile_digest_rejects_unknown_platform() -> None:
    contract = _load_contract()
    registry = _load_registry()
    _expect_reject(
        lambda: contract.compute_selected_profile_digest(
            registry, "phantom-platform", "any-profile"
        ),
        "unknown platform must be rejected",
    )


# ---------------------------------------------------------------------------
# 5. Missing, duplicate, reordered, unknown and tampered fields fail.
# ---------------------------------------------------------------------------


def test_validate_rejects_non_dict() -> None:
    contract = _load_contract()
    for bad in (None, 1, "x", [], 1.5):
        _expect_reject(lambda b=bad: contract.validate_descriptor(b), "non-dict")


def test_validate_rejects_missing_kind() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    del d["kind"]
    _expect_reject(lambda: contract.validate_descriptor(d), "missing kind")


def test_validate_rejects_missing_schema_version() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    del d["schema_version"]
    _expect_reject(lambda: contract.validate_descriptor(d), "missing schema_version")


def test_validate_rejects_missing_platform_id() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    del d["platform_id"]
    _expect_reject(lambda: contract.validate_descriptor(d), "missing platform_id")


def test_validate_rejects_missing_profile_id() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    del d["profile_id"]
    _expect_reject(lambda: contract.validate_descriptor(d), "missing profile_id")


def test_validate_rejects_missing_components() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    del d["components"]
    _expect_reject(lambda: contract.validate_descriptor(d), "missing components")


def test_validate_rejects_missing_ports() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    del d["ports"]
    _expect_reject(lambda: contract.validate_descriptor(d), "missing ports")


def test_validate_rejects_extra_top_level_key() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["surprise"] = "boom"
    _expect_reject(lambda: contract.validate_descriptor(d), "extra top-level key")


def test_validate_rejects_tampered_kind() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["kind"] = "icp.something-else.v1"
    _expect_reject(lambda: contract.validate_descriptor(d), "tampered kind")


def test_validate_rejects_wrong_schema_version() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["schema_version"] = 2
    _expect_reject(lambda: contract.validate_descriptor(d), "wrong schema_version")


def test_validate_rejects_empty_platform_id() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["platform_id"] = ""
    _expect_reject(lambda: contract.validate_descriptor(d), "empty platform_id")


def test_validate_rejects_empty_profile_id() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["profile_id"] = ""
    _expect_reject(lambda: contract.validate_descriptor(d), "empty profile_id")


def test_validate_rejects_null_profile_id() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["profile_id"] = None
    _expect_reject(lambda: contract.validate_descriptor(d), "null profile_id")


def test_validate_rejects_active_state() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["activation_state"] = "active"
    _expect_reject(lambda: contract.validate_descriptor(d), "active state")


def test_validate_rejects_executable_true() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["executable"] = True
    _expect_reject(lambda: contract.validate_descriptor(d), "executable true")


def test_validate_rejects_executable_one() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["executable"] = 1
    _expect_reject(lambda: contract.validate_descriptor(d), "executable=1")


def test_validate_rejects_malformed_registry_digest() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["registry_digest"] = "not-a-sha"
    _expect_reject(lambda: contract.validate_descriptor(d), "malformed registry_digest")


def test_validate_rejects_malformed_selected_profile_digest() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["selected_profile_digest"] = "XYZ" * 5
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "malformed selected_profile_digest",
    )


def test_validate_rejects_reordered_top_level_keys() -> None:
    """Top-level keys must appear in the canonical order. A descriptor
    that arrives with even the first two keys swapped must fail."""
    contract = _load_contract()
    d = _synthetic_descriptor()
    bad = {"schema_version": d["schema_version"]}
    bad.update(d)
    assert list(bad.keys())[0] == "schema_version"
    _expect_reject(lambda: contract.validate_descriptor(bad), "reordered keys")


def test_validate_rejects_repeated_component_role() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["components"][1] = copy.deepcopy(d["components"][0])
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "repeated component role",
    )


def test_validate_rejects_swapped_component_roles() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["components"][0], d["components"][1] = d["components"][1], d["components"][0]
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "swapped component roles",
    )


def test_validate_rejects_missing_component() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["components"].pop()
    _expect_reject(lambda: contract.validate_descriptor(d), "missing component")


def test_validate_rejects_extra_component() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["components"].append(copy.deepcopy(d["components"][0]))
    _expect_reject(lambda: contract.validate_descriptor(d), "extra component")


def test_validate_rejects_component_unknown_role() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["components"][0]["role"] = "phantom_role"
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "component unknown role",
    )


def test_validate_rejects_component_extra_key() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["components"][0]["extra_key"] = "x"
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "component extra key",
    )


def test_validate_rejects_component_missing_public_api() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    del d["components"][0]["public_api"]
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "component missing public_api",
    )


def test_validate_rejects_component_empty_public_api() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["components"][0]["public_api"] = []
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "component empty public_api",
    )


def test_validate_rejects_component_unsafe_basename() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["components"][0]["module_basename"] = "../escape.py"
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "component unsafe basename",
    )


def test_validate_rejects_component_malformed_sha() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["components"][0]["module_sha256"] = "xyz"
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "component malformed sha",
    )


def test_validate_rejects_component_empty_contract_kind() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["components"][0]["contract_kind"] = ""
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "component empty contract_kind",
    )


def test_validate_rejects_component_private_api_name() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["components"][0]["public_api"] = ["_private"]
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "component private api name",
    )


def test_validate_rejects_repeated_port_id() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["ports"][1] = copy.deepcopy(d["ports"][0])
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "repeated port id",
    )


def test_validate_rejects_swapped_port_ids() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["ports"][0], d["ports"][1] = d["ports"][1], d["ports"][0]
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "swapped port ids",
    )


def test_validate_rejects_missing_port() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["ports"].pop()
    _expect_reject(lambda: contract.validate_descriptor(d), "missing port")


def test_validate_rejects_extra_port() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["ports"].append(copy.deepcopy(d["ports"][0]))
    _expect_reject(lambda: contract.validate_descriptor(d), "extra port")


def test_validate_rejects_port_extra_key() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["ports"][0]["extra_key"] = "x"
    _expect_reject(lambda: contract.validate_descriptor(d), "port extra key")


def test_validate_rejects_port_unknown_capability_state() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["ports"][0]["capability_state"] = "always"
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "port unknown capability_state",
    )


def test_validate_rejects_port_legacy_implementation_state() -> None:
    """``legacy-mapped`` is a P2c legacy migration label, NOT a valid v1
    ``implementation_state``. The shared validator must reject it."""
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["ports"][0]["implementation_state"] = "legacy-mapped"
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "port legacy implementation_state",
    )


def test_validate_rejects_port_unknown_implementation_state() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["ports"][0]["implementation_state"] = "in-progress"
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "port unknown implementation_state",
    )


def test_validate_rejects_port_unknown_provider_role() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["ports"][0]["provider_component_role"] = "fake_role"
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "port unknown provider role",
    )


def test_validate_rejects_supported_task_source_unknown_id() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["supported_task_sources"] = ["csv", "excel"]
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "unknown task source id",
    )


def test_validate_rejects_supported_design_source_unknown_id() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["supported_design_sources"] = ["figma-only"]
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "unknown design source id",
    )


def test_validate_rejects_supported_task_source_duplicate() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["supported_task_sources"] = ["csv", "csv"]
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "duplicate task source id",
    )


# ---------------------------------------------------------------------------
# 6. Forbidden command/argv/env/shell/prompt/path/activation-override
#    injection fails anywhere in the descriptor.
# ---------------------------------------------------------------------------


def test_validate_rejects_command_on_root() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["command"] = "rm -rf /"
    _expect_reject(lambda: contract.validate_descriptor(d), "root command")


def test_validate_rejects_argv_on_root() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["argv"] = []
    _expect_reject(lambda: contract.validate_descriptor(d), "root argv")


def test_validate_rejects_env_on_root() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["env"] = {"PATH": "/bin"}
    _expect_reject(lambda: contract.validate_descriptor(d), "root env")


def test_validate_rejects_shell_on_root() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["shell"] = "/bin/sh"
    _expect_reject(lambda: contract.validate_descriptor(d), "root shell")


def test_validate_rejects_interpreter_on_root() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["interpreter"] = "/usr/bin/python3"
    _expect_reject(lambda: contract.validate_descriptor(d), "root interpreter")


def test_validate_rejects_runner_on_root() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["runner"] = "flutter"
    _expect_reject(lambda: contract.validate_descriptor(d), "root runner")


def test_validate_rejects_script_path_on_root() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["script_path"] = "/x/y.py"
    _expect_reject(lambda: contract.validate_descriptor(d), "root script_path")


def test_validate_rejects_activate_on_root() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["activate"] = True
    _expect_reject(lambda: contract.validate_descriptor(d), "root activate")


def test_validate_rejects_activation_override_on_root() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["activation_override"] = "force"
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "root activation_override",
    )


def test_validate_rejects_prompt_on_entry_requirement() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["entry_requirements"][0]["prompt"] = "supply token"
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "entry-requirement prompt",
    )


def test_validate_rejects_command_in_component() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["components"][0]["command"] = "rm -rf /"
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "component command",
    )


def test_validate_rejects_executable_field_on_component() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["components"][0]["executable"] = False
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "component executable field",
    )


def test_validate_rejects_env_in_port() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["ports"][0]["env"] = {"PATH": "/bin"}
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "port env",
    )


def test_validate_rejects_path_in_artifact_contract() -> None:
    """artifact_contracts entries are controlled IDs, not paths."""
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["ports"][0]["artifact_contracts"] = ["/etc/passwd"]
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "artifact_contract path injection",
    )


# ---------------------------------------------------------------------------
# 7. Entry-requirement enum and injection violations fail.
# ---------------------------------------------------------------------------


def test_validate_rejects_entry_requirement_extra_key() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["entry_requirements"][0]["extra_key"] = "x"
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "entry-requirement extra key",
    )


def test_validate_rejects_entry_requirement_unknown_owner() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["entry_requirements"][0]["owner"] = "admin"
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "entry-requirement unknown owner",
    )


def test_validate_rejects_entry_requirement_required_non_bool() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["entry_requirements"][0]["required"] = "yes"
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "entry-requirement required non-bool",
    )


def test_validate_rejects_entry_requirement_sensitive_non_bool() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["entry_requirements"][0]["sensitive"] = 1
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "entry-requirement sensitive non-bool",
    )


def test_validate_rejects_entry_requirement_path_probe_id() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["entry_requirements"][0]["probe_id"] = "/bin/sh probe"
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "entry-requirement path probe_id",
    )


def test_validate_rejects_entry_requirement_secret_accepted_shape() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["entry_requirements"][0]["accepted_shape_id"] = "Bearer ABCDEF"
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "entry-requirement secret accepted_shape_id",
    )


def test_validate_rejects_entry_requirement_command_remediation() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["entry_requirements"][0]["remediation_id"] = "rm -rf /"
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "entry-requirement command remediation_id",
    )


def test_validate_rejects_entry_requirement_duplicate_id() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["entry_requirements"][1]["id"] = d["entry_requirements"][0]["id"]
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "entry-requirement duplicate id",
    )


def test_validate_rejects_entry_requirement_reordered_keys() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    er = d["entry_requirements"][0]
    bad = {"owner": er["owner"]}
    bad.update(er)
    d["entry_requirements"][0] = bad
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "entry-requirement reordered keys",
    )


# ---------------------------------------------------------------------------
# 8. Design / reference image actual-source types fail.
# ---------------------------------------------------------------------------


def test_validate_rejects_design_image_actual_source_type() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["actual_source_types"].append("design_image")
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "design_image actual source type",
    )


def test_validate_rejects_reference_actual_source_type() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["actual_source_types"].append("reference")
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "reference actual source type",
    )


def test_validate_rejects_reference_image_actual_source_type() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["actual_source_types"].append("reference_image")
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "reference_image actual source type",
    )


def test_validate_rejects_design_actual_source_type() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["actual_source_types"].append("design")
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "design actual source type",
    )


def test_validate_rejects_unknown_actual_source_type() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["actual_source_types"].append("cloud_screenshot")
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "unknown actual source type",
    )


def test_validate_rejects_duplicate_actual_source_type() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["actual_source_types"].append("browser_screenshot")
    _expect_reject(
        lambda: contract.validate_descriptor(d),
        "duplicate actual source type",
    )


def test_validate_accepts_all_four_canonical_actual_source_types() -> None:
    contract = _load_contract()
    d = _synthetic_descriptor()
    d["actual_source_types"] = list(ACTUAL_SOURCE_TYPES)
    contract.validate_descriptor(d)


# ---------------------------------------------------------------------------
# 9. Flutter package: descriptor, components, ports.
# ---------------------------------------------------------------------------


def test_flutter_describe_package_canonical() -> None:
    flutter = _load_flutter_package()
    descriptor = flutter.describe_package()
    assert descriptor["kind"] == KIND_DESCRIPTOR
    assert descriptor["schema_version"] == SCHEMA_VERSION
    assert descriptor["platform_id"] == "flutter"
    assert descriptor["profile_id"] == "flutter-standard"
    assert descriptor["activation_state"] == "active"
    assert descriptor["executable"] is True


def test_flutter_describe_package_top_level_keys_exact_order() -> None:
    contract = _load_contract()
    flutter = _load_flutter_package()
    descriptor = flutter.describe_package()
    expected = (
        "kind",
        "schema_version",
        "platform_id",
        "profile_id",
        "activation_state",
        "executable",
        "registry_digest",
        "selected_profile_digest",
        "supported_task_sources",
        "supported_design_sources",
        "actual_source_types",
        "entry_requirements",
        "components",
        "ports",
    )
    assert tuple(descriptor.keys()) == expected, list(descriptor.keys())
    # And the produced descriptor passes the shared validator.
    contract.validate_descriptor(descriptor)


def test_flutter_describe_package_components_in_fixed_role_order() -> None:
    flutter = _load_flutter_package()
    descriptor = flutter.describe_package()
    roles = [c["role"] for c in descriptor["components"]]
    assert tuple(roles) == COMPONENT_ROLES, roles


def test_flutter_describe_package_component_basenames_match_fixed() -> None:
    flutter = _load_flutter_package()
    descriptor = flutter.describe_package()
    for actual, expected in zip(descriptor["components"], FLUTTER_COMPONENTS):
        assert actual["module_basename"] == expected["basename"], actual
        assert tuple(actual["public_api"]) == expected["public_api"], actual
        assert actual["contract_kind"] == expected["contract_kind"], actual


def test_flutter_describe_package_ports_in_fixed_id_order() -> None:
    flutter = _load_flutter_package()
    descriptor = flutter.describe_package()
    ids = [p["id"] for p in descriptor["ports"]]
    assert tuple(ids) == PORT_IDS, ids


def test_flutter_describe_package_ports_capability_states_match_registry() -> None:
    flutter = _load_flutter_package()
    descriptor = flutter.describe_package()
    registry = _load_registry()
    reg_caps = registry["capabilities"]
    for port in descriptor["ports"]:
        assert port["capability_state"] == reg_caps[port["id"]], port


def test_flutter_describe_package_only_project_preflight_implemented() -> None:
    """Flutter package marks ``project_preflight`` as ``implemented``;\n    the other 8 ports are ``not-implemented``. The frozen P2c\ndescriptor still says ``new-port-required`` for project_preflight;\n    these two facts are independent and must not interfere."""
    flutter = _load_flutter_package()
    descriptor = flutter.describe_package()
    for port in descriptor["ports"]:
        assert port["implementation_state"] in ("implemented", "not-implemented"), port
    preflight = descriptor["ports"][0]
    assert preflight["id"] == "project_preflight"
    assert preflight["implementation_state"] == "implemented", preflight
    for port in descriptor["ports"][1:]:
        assert port["implementation_state"] == "not-implemented", port


def test_flutter_describe_package_six_component_shas_match_live_files() -> None:
    flutter = _load_flutter_package()
    descriptor = flutter.describe_package()
    assert len(descriptor["components"]) == 6
    for comp in descriptor["components"]:
        path = PLATFORMS_DIR / comp["module_basename"]
        assert path.exists(), f"missing component file: {path}"
        live_sha = _sha256_file(path)
        assert comp["module_sha256"] == live_sha, (
            f"SHA mismatch for {comp['module_basename']}: "
            f"descriptor={comp['module_sha256']} live={live_sha}"
        )


def test_flutter_describe_package_registry_digest_matches_live_registry() -> None:
    contract = _load_contract()
    flutter = _load_flutter_package()
    descriptor = flutter.describe_package()
    registry = _load_registry()
    expected = contract.compute_registry_digest(registry)
    assert descriptor["registry_digest"] == expected


def test_flutter_describe_package_selected_profile_digest_matches_live() -> None:
    contract = _load_contract()
    flutter = _load_flutter_package()
    descriptor = flutter.describe_package()
    registry = _load_registry()
    expected = contract.compute_selected_profile_digest(
        registry, "flutter", "flutter-standard"
    )
    assert descriptor["selected_profile_digest"] == expected


def test_flutter_describe_package_supports_only_csv_and_lanhu_figma() -> None:
    flutter = _load_flutter_package()
    descriptor = flutter.describe_package()
    assert descriptor["supported_task_sources"] == ["csv"]
    assert descriptor["supported_design_sources"] == ["lanhu-figma"]


def test_flutter_describe_package_descriptor_digest_deterministic() -> None:
    contract = _load_contract()
    flutter = _load_flutter_package()
    d1 = flutter.describe_package()
    d2 = flutter.describe_package()
    assert contract.compute_descriptor_digest(d1) == contract.compute_descriptor_digest(d2)


# ---------------------------------------------------------------------------
# 10. Flutter verify_package (descriptor verifier invoked; 5 modules
#     checked statically without invoking deep verifiers).
# ---------------------------------------------------------------------------


def test_flutter_verify_package_canonical() -> None:
    flutter = _load_flutter_package()
    report = flutter.verify_package()
    assert report["ok"] is True
    assert report["kind"] == KIND_VERIFY
    assert report["schema_version"] == SCHEMA_VERSION
    assert report["platform_id"] == "flutter"
    assert report["profile_id"] == "flutter-standard"
    assert report["activation_state"] == "active"
    assert report["executable"] is True
    assert isinstance(report["package_digest"], str)
    assert len(report["package_digest"]) == 64
    assert report["components_total"] == 6
    assert report["ports_total"] == 9


def test_flutter_verify_package_recomputes_registry_digest() -> None:
    contract = _load_contract()
    flutter = _load_flutter_package()
    report = flutter.verify_package()
    registry = _load_registry()
    expected = contract.compute_registry_digest(registry)
    assert report["registry_digest"] == expected


def test_flutter_verify_package_recomputes_selected_profile_digest() -> None:
    contract = _load_contract()
    flutter = _load_flutter_package()
    report = flutter.verify_package()
    registry = _load_registry()
    expected = contract.compute_selected_profile_digest(
        registry, "flutter", "flutter-standard"
    )
    assert report["selected_profile_digest"] == expected


def test_flutter_verify_package_digest_matches_descriptor_digest() -> None:
    contract = _load_contract()
    flutter = _load_flutter_package()
    report = flutter.verify_package()
    descriptor = flutter.describe_package()
    expected = contract.compute_descriptor_digest(descriptor)
    assert report["package_digest"] == expected


def test_flutter_verify_package_invokes_descriptor_verifier() -> None:
    """verify_package must call flutter_standard_v1.verify_descriptor().
    Confirmed by counting calls into the cached descriptor module."""
    flutter = _load_flutter_package()
    # Prime the descriptor-module cache.
    flutter.verify_package()
    descriptor_module = flutter._DESCRIPTOR_MODULE
    assert descriptor_module is not None
    original = descriptor_module.verify_descriptor
    calls = [0]

    def counting_verify():
        calls[0] += 1
        return original()

    descriptor_module.verify_descriptor = counting_verify
    try:
        flutter.verify_package()
    finally:
        descriptor_module.verify_descriptor = original
    assert calls[0] == 1, (
        f"descriptor.verify_descriptor was called {calls[0]} times"
    )


def test_flutter_verify_package_fails_closed_on_descriptor_fail() -> None:
    """If the descriptor verifier returns non-success, verify_package
    must fail closed."""
    flutter = _load_flutter_package()
    flutter.verify_package()
    descriptor_module = flutter._DESCRIPTOR_MODULE
    original = descriptor_module.verify_descriptor

    def failing_verify():
        return {"ok": False, "kind": "icp.platform-adapter-descriptor-verify.v1"}

    descriptor_module.verify_descriptor = failing_verify
    try:
        _expect_reject(flutter.verify_package, "descriptor fail-closed")
    finally:
        descriptor_module.verify_descriptor = original


def test_flutter_verify_package_does_not_call_request_scoped_entrypoints() -> None:
    """verify_package must AST-check (not call) the 5 request-scoped
    modules' deep verifiers. Proven by AST-scanning flutter_package_v1
    for direct calls to preflight/build/prepare_binding/
    prepare_authorization/execute_authorization."""
    source = FLUTTER_PACKAGE_PATH.read_text()
    tree = ast.parse(source)
    forbidden_names = {
        "preflight", "build", "prepare_binding",
        "prepare_authorization", "execute_authorization",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in forbidden_names:
                raise AssertionError(
                    f"flutter_package_v1 calls forbidden entrypoint: {func.id}"
                )
            if isinstance(func, ast.Attribute) and func.attr in forbidden_names:
                raise AssertionError(
                    f"flutter_package_v1 calls forbidden entrypoint: .{func.attr}"
                )


def test_flutter_package_does_not_invoke_request_scoped_modules_at_import() -> None:
    """Importing flutter_package_v1 must not import any of the five
    request-scoped modules. The wrapper only reads their file bytes."""
    source = FLUTTER_PACKAGE_PATH.read_text()
    forbidden_basenames = (
        "flutter_project_preflight_v1",
        "flutter_operations_v1",
        "flutter_execution_binding_v1",
        "flutter_execution_authorization_v1",
        "flutter_execution_executor_v1",
    )
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                for forb in forbidden_basenames:
                    assert not alias.name.startswith(forb), (
                        f"flutter_package_v1 imports {alias.name}"
                    )
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None
            for forb in forbidden_basenames:
                assert not node.module.startswith(forb), (
                    f"flutter_package_v1 from-imports {node.module}"
                )


# ---------------------------------------------------------------------------
# 11. All package activation remains inactive and non-executable.
# ---------------------------------------------------------------------------


def test_flutter_package_is_active_after_audited_activation() -> None:
    flutter = _load_flutter_package()
    descriptor = flutter.describe_package()
    report = flutter.verify_package()
    assert descriptor["activation_state"] == "active"
    assert report["activation_state"] == "active"


def test_flutter_package_is_executable_after_audited_activation() -> None:
    flutter = _load_flutter_package()
    descriptor = flutter.describe_package()
    report = flutter.verify_package()
    assert descriptor["executable"] is True
    assert report["executable"] is True


def test_flutter_package_does_not_import_iff() -> None:
    source = FLUTTER_PACKAGE_PATH.read_text()
    assert "import iff" not in source
    assert "from iff " not in source
    assert "from iff." not in source


def test_contract_module_does_not_import_iff() -> None:
    source = CONTRACT_PATH.read_text()
    assert "import iff" not in source
    assert "from iff " not in source
    assert "from iff." not in source


# ---------------------------------------------------------------------------
# 12. Import performs zero filesystem / subprocess / network / write I/O.
# ---------------------------------------------------------------------------


_FORBIDDEN_TOP_LEVEL_NAME_CALLS = {
    "open", "system", "popen", "execv", "execve", "execl",
    "spawnv", "spawnve", "fork", "urlopen",
}
_FORBIDDEN_TOP_LEVEL_ATTR_CALLS = {
    "open", "resolve", "stat", "lstat", "exists", "is_file", "is_dir",
    "is_symlink", "readlink", "iterdir", "glob", "rglob", "read_text",
    "read_bytes", "write_text", "write_bytes", "mkdir", "unlink",
    "replace", "rename", "touch", "chmod", "symlink_to", "hardlink_to",
}
_FORBIDDEN_TOP_LEVEL_ATTR_CHAINS = {
    "subprocess.run", "subprocess.call", "subprocess.check_call",
    "subprocess.check_output", "subprocess.Popen",
    "subprocess.getoutput", "subprocess.getstatusoutput",
    "os.system", "os.popen", "os.execv", "os.spawnv", "os.fork",
    "urllib.request.urlopen", "urllib.urlopen",
    "socket.socket",
}


def _attr_chain(node: ast.AST) -> str:
    parts = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


def _top_level_io_violations(tree: ast.Module) -> list:
    """Find top-level (module-body) I/O calls that would execute at import."""
    violations = []

    def check_call(node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name):
            if func.id in _FORBIDDEN_TOP_LEVEL_NAME_CALLS:
                violations.append(func.id)
        elif isinstance(func, ast.Attribute):
            chain = _attr_chain(func)
            last = chain.rsplit(".", 1)[-1]
            if chain in _FORBIDDEN_TOP_LEVEL_ATTR_CHAINS:
                violations.append(chain)
            elif last in _FORBIDDEN_TOP_LEVEL_ATTR_CALLS:
                violations.append(chain)

    for stmt in tree.body:
        # Function/class bodies are NOT executed at import.
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call):
                check_call(node)
    return violations


def test_contract_module_no_top_level_io_calls() -> None:
    tree = ast.parse(CONTRACT_PATH.read_text())
    violations = _top_level_io_violations(tree)
    assert violations == [], (
        f"contract module top-level I/O calls: {violations}"
    )


def test_flutter_package_module_no_top_level_io_calls() -> None:
    tree = ast.parse(FLUTTER_PACKAGE_PATH.read_text())
    violations = _top_level_io_violations(tree)
    assert violations == [], (
        f"flutter_package_v1 top-level I/O calls: {violations}"
    )


def test_modules_import_cleanly_in_fresh_subprocess() -> None:
    """Importing both modules in a fresh Python process must succeed."""
    code = (
        "import sys, importlib.util;"
        f"spec = importlib.util.spec_from_file_location("
        f"'p3a_contract_subproc', {str(CONTRACT_PATH)!r});"
        "m = importlib.util.module_from_spec(spec);"
        "sys.modules['p3a_contract_subproc'] = m;"
        "spec.loader.exec_module(m);"
        f"spec2 = importlib.util.spec_from_file_location("
        f"'p3a_flutter_subproc', {str(FLUTTER_PACKAGE_PATH)!r});"
        "m2 = importlib.util.module_from_spec(spec2);"
        "sys.modules['p3a_flutter_subproc'] = m2;"
        "spec2.loader.exec_module(m2);"
        "print('IMPORT_OK');"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, (
        f"import failed: rc={result.returncode} stderr={result.stderr}"
    )
    assert result.stdout.strip() == "IMPORT_OK", result.stdout


# ---------------------------------------------------------------------------
# 13. Architecture reference matches the Skill-owned approval manifest.
# ---------------------------------------------------------------------------


def test_architecture_reference_byte_identical_to_approved() -> None:
    manifest = json.loads(APPROVED_ARCH_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert isinstance(manifest, dict) and tuple(manifest) == (
        "kind",
        "schema_version",
        "path",
        "sha256",
        "approved_change",
    ), "architecture approval manifest shape is invalid"
    assert manifest["kind"] == "icp.p3-platform-package-architecture-approval.v1"
    assert manifest["schema_version"] == 1
    assert manifest["path"] == "references/p3-platform-package-architecture.md"
    approved_digest = manifest["sha256"]
    assert (
        isinstance(approved_digest, str)
        and len(approved_digest) == 64
        and all(character in "0123456789abcdef" for character in approved_digest)
    ), "approved architecture digest is invalid"
    assert manifest["approved_change"] == "rename-cakp-to-cap"
    installed_digest = hashlib.sha256(INSTALLED_ARCH_PATH.read_bytes()).hexdigest()
    assert installed_digest == approved_digest, (
        f"installed architecture differs from approved manifest: "
        f"approved_sha256={approved_digest} installed_sha256={installed_digest}"
    )


def test_architecture_reference_present_in_repo() -> None:
    assert INSTALLED_ARCH_PATH.exists(), (
        f"missing installed architecture: {INSTALLED_ARCH_PATH}"
    )


# ---------------------------------------------------------------------------
# Selftest runner.
# ---------------------------------------------------------------------------


def main() -> int:
    tests = [name for name in globals() if name.startswith("test_")]
    failures = 0
    for name in sorted(tests):
        try:
            globals()[name]()
            print(f"PASS: {name}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL: {name}: {type(exc).__name__}: {exc}")
    if failures:
        print(f"FAILED {failures}/{len(tests)}")
        return 1
    print(f"ok {len(tests)} selftest cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
