#!/usr/bin/env python3
"""ICP P3b1b1 platform-package resolver / selection focused RED -> GREEN self-test.

Covers three pure / in-memory production modules and the live package
index artifact:

* ``icp/scripts/platform_package_resolver_v1.py``
* ``icp/scripts/freeze_platform_package_selection_v1.py``
* ``icp/scripts/verify_platform_package_selection_v1.py``
* ``icp/references/platform_packages_v1.json``

Every platform remains ``inactive`` and every selection / resolution /
verification is ``executable=False``. This self-test performs zero
filesystem write, locking, CAS, claim, writeback, probe execution,
worker launch, package wrapper import, or production publication. It
uses one short subprocess only for the import-freshness smoke check.

RED -> GREEN discipline: this self-test was created BEFORE the three
production modules and the index artifact. The first run fails for
module / index absence (``FileNotFoundError``) -- that is the recorded
RED reason. After implementation, the self-test must pass cleanly.

Coverage matrix: closed public API / signatures; exact ordered schemas
for index / resolution / selection / verification; missing / extra /
reordered keys, kinds, versions, digests, safe IDs, enums; recursive
exact-key injection rejection without substring false positives; live
index contains exactly the current Flutter row with live module SHA
and live descriptor digest, inactive / non-executable; generic
synthetic non-Flutter index / resolution accepted (no Flutter literal
in production); unknown / duplicate / unsorted index entries; unsafe
basename / path escape; module bytes drift, descriptor drift, registry
drift, selected-profile drift, platform / profile mismatch; producer
mapping exact IDs / order / types; producer digest drift / missing /
extra / reorder / unknown-field tamper; adjacent readiness / manifest /
package-verification digest drift; selection copied-field / active /
executable / verification tamper; determinism + input immutability; AST
purity across all three modules (no dynamic import / pathlib / sys /
os / file I/O / CLI / subprocess / network / env, no platform-specific
production literals / branches, static private project imports only);
no production module imports a package wrapper.

Run directly:

    PYTHONDONTWRITEBYTECODE=1 \\
        python3 icp/scripts/selftest_p3b1_platform_package_selection.py
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
from pathlib import Path
from typing import Any, Callable

ICP_ROOT = Path(__file__).resolve().parents[1]
ICP_SCRIPTS = Path(__file__).resolve().parent
PLATFORMS_DIR = ICP_SCRIPTS / "platforms"
RESOLVER_PATH = ICP_SCRIPTS / "platform_package_resolver_v1.py"
FREEZER_PATH = ICP_SCRIPTS / "freeze_platform_package_selection_v1.py"
VERIFIER_PATH = ICP_SCRIPTS / "verify_platform_package_selection_v1.py"
INDEX_PATH = ICP_ROOT / "references" / "platform_packages_v1.json"
CONTRACT_PATH = PLATFORMS_DIR / "platform_package_contract_v1.py"
FLUTTER_PACKAGE_PATH = PLATFORMS_DIR / "flutter_package_v1.py"
VUE_PACKAGE_PATH = PLATFORMS_DIR / "vue_package_v1.py"
REGISTRY_PATH = ICP_ROOT / "references" / "registries.json"

KIND_INDEX = "icp.platform-packages-index.v1"
KIND_RESOLUTION = "icp.platform-package-resolution.v1"
KIND_SELECTION = "icp.platform-package-selection.v1"
KIND_VERIFICATION = "icp.platform-package-selection-verification.v1"
SCHEMA_VERSION = 1
ACTIVATION_STATE_INACTIVE = "inactive"

INDEX_KEYS = ("kind", "schema_version", "packages")
INDEX_ROW_KEYS = (
    "platform_id", "profile_id",
    "package_module_basename", "package_module_sha256",
    "package_descriptor_digest",
)
RESOLUTION_KEYS = (
    "kind", "schema_version",
    "platform_id", "profile_id",
    "package_module_basename", "package_module_sha256",
    "package_index_digest", "package_descriptor_digest",
    "registry_digest", "selected_profile_digest",
    "activation_state", "executable",
)
SELECTION_KEYS = (
    "kind", "schema_version",
    "platform_id", "profile_id",
    "entry_readiness_report_digest",
    "selection_manifest_digest",
    "package_index_digest",
    "package_descriptor_digest",
    "package_verification_digest",
    "registry_digest",
    "selected_profile_digest",
    "package_module_basename",
    "package_module_sha256",
    "activation_state", "executable",
    "producer_script_digests",
)
PRODUCER_ROW_KEYS = ("id", "basename", "sha256")
VERIFICATION_KEYS = (
    "kind", "schema_version", "selection_digest",
    "platform_id", "profile_id", "verified",
)

PRODUCER_SPECS = (
    ("entry-readiness-v1", "entry_readiness_v1.py"),
    ("platform-package-resolver-v1", "platform_package_resolver_v1.py"),
    ("freeze-platform-package-selection-v1",
     "freeze_platform_package_selection_v1.py"),
    ("verify-platform-package-selection-v1",
     "verify_platform_package_selection_v1.py"),
)
PRODUCER_IDS = tuple(spec[0] for spec in PRODUCER_SPECS)

DIGEST_ENTRY_READINESS = "aa" * 32
DIGEST_SELECTION_MANIFEST = "bb" * 32
DIGEST_PACKAGE_VERIFICATION = "cc" * 32
DIGEST_INDEX = "dd" * 32
DIGEST_DESCRIPTOR = "ee" * 32
DIGEST_REGISTRY = "ff" * 32
DIGEST_SELECTED_PROFILE = "11" * 32
DIGEST_MODULE = "2a" * 32
DIGEST_ALT = "33" * 32

INJECTION_FIELDS = (
    "command", "argv", "shell", "interpreter", "env", "runner", "args",
    "program", "cmd", "subprocess", "exec", "run", "script_path",
    "script_runner", "activate", "activation_command",
    "activation_override", "prompt", "prompt_template", "path",
    "task_ref", "row_title", "design_url", "secret", "token",
    "password", "credential", "api_key", "claim_ack", "writeback_ack",
    "row_payload",
)
LEGIT_VALUE_WITH_SUBSTRING = "design_url_handler"
PLATFORM_LITERALS = (
    "flutter", "dart", "vue", "nextjs", "next.js", "ios", "android",
    "swift", "objc", "kotlin", "java", "gradle", "xcode", "simctl",
    "adb", "pubspec", "lanhu", "figma",
)


# ---------------------------------------------------------------------------
# Module loaders and tiny helpers.
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


def _load_resolver():
    return _load("platform_package_resolver_v1_selftest_b1b", RESOLVER_PATH)


def _load_freezer():
    return _load(
        "freeze_platform_package_selection_v1_selftest_b1b", FREEZER_PATH
    )


def _load_verifier():
    return _load(
        "verify_platform_package_selection_v1_selftest_b1b", VERIFIER_PATH
    )


def _load_contract():
    return _load("platform_package_contract_v1_selftest_b1b", CONTRACT_PATH)


def _load_flutter_package():
    return _load("flutter_package_v1_selftest_b1b", FLUTTER_PACKAGE_PATH)


def _load_vue_package():
    return _load("vue_package_v1_selftest_b1b", VUE_PACKAGE_PATH)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(payload: dict) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _expect_reject(callable_: Callable, label: str) -> None:
    try:
        callable_()
    except Exception:  # noqa: BLE001
        return
    raise AssertionError(f"{label}: expected rejection, got success")


def _reordered(src: dict, key_order: tuple) -> dict:
    return {key: src[key] for key in reversed(key_order)}


def _read_registry() -> dict:
    return json.loads(REGISTRY_PATH.read_bytes())


def _read_index() -> dict:
    if not INDEX_PATH.exists():
        raise FileNotFoundError(f"index not found: {INDEX_PATH}")
    return json.loads(INDEX_PATH.read_bytes())


# ---------------------------------------------------------------------------
# Independent synthetic builders (do not import the modules under test).
# ---------------------------------------------------------------------------


def _synthetic_descriptor(
    *,
    platform_id: str = "synthetic",
    profile_id: str = "synthetic-default",
    registry_digest: str = DIGEST_REGISTRY,
    selected_profile_digest: str = DIGEST_SELECTED_PROFILE,
    activation_state: str = ACTIVATION_STATE_INACTIVE,
    executable: bool = False,
) -> dict:
    """Build a minimal valid synthetic non-Flutter descriptor."""
    roles_apis = (
        ("descriptor", ("describe", "verify_descriptor")),
        ("project_preflight", ("preflight",)),
        ("operation_plans", ("build",)),
        ("binding", ("prepare_binding",)),
        ("authorization", ("prepare_authorization",)),
        ("executor", ("execute_authorization",)),
    )
    components = [
        {
            "role": role,
            "module_basename": f"synthetic_{role}_v1.py",
            "module_sha256": DIGEST_MODULE,
            "contract_kind": f"icp.synthetic-{role}.v1",
            "public_api": list(api),
        }
        for role, api in roles_apis
    ]
    port_specs = (
        ("project_preflight", "required", "implemented", "project_preflight"),
        ("visible_codegen", "required", "not-implemented", "operation_plans"),
        ("fixture_codegen", "required", "not-implemented", "operation_plans"),
        ("trace_harness", "optional-with-shared-policy",
         "not-implemented", "operation_plans"),
        ("packaging", "required", "not-implemented", "operation_plans"),
        ("test_runner", "required", "not-implemented", "operation_plans"),
        ("runtime_capture", "optional-with-shared-policy",
         "not-implemented", "operation_plans"),
        ("project_gates", "required", "not-implemented", "operation_plans"),
        ("fan_in", "required", "not-implemented", "operation_plans"),
    )
    ports = [
        {
            "id": pid, "capability_state": cap,
            "implementation_state": impl,
            "provider_component_role": prov, "artifact_contracts": [],
        }
        for (pid, cap, impl, prov) in port_specs
    ]
    return {
        "kind": "icp.platform-package-descriptor.v1",
        "schema_version": 1,
        "platform_id": platform_id,
        "profile_id": profile_id,
        "activation_state": activation_state,
        "executable": executable,
        "registry_digest": registry_digest,
        "selected_profile_digest": selected_profile_digest,
        "supported_task_sources": ["csv"],
        "supported_design_sources": ["lanhu-figma"],
        "actual_source_types": [],
        "entry_requirements": [],
        "components": components,
        "ports": ports,
    }


def _synthetic_index_row(
    *, platform_id: str = "synthetic", profile_id: str = "synthetic-default",
    basename: str = "synthetic_package_v1.py",
    module_sha: str = DIGEST_MODULE,
    descriptor_digest: str = DIGEST_DESCRIPTOR,
) -> dict:
    return {
        "platform_id": platform_id, "profile_id": profile_id,
        "package_module_basename": basename,
        "package_module_sha256": module_sha,
        "package_descriptor_digest": descriptor_digest,
    }


def _synthetic_index(rows: list[dict] | None = None) -> dict:
    if rows is None:
        rows = [_synthetic_index_row()]
    return {
        "kind": KIND_INDEX, "schema_version": SCHEMA_VERSION,
        "packages": list(rows),
    }


def _synthetic_module_bytes() -> bytes:
    return b"# synthetic package module bytes for resolver tests\n"


def _resolve_synthetic_kwargs(
    *, resolver_module, descriptor: dict | None = None,
    index_rows: list[dict] | None = None,
    module_bytes: bytes | None = None,
    platform_id: str = "synthetic",
    profile_id: str = "synthetic-default",
) -> dict:
    """Build resolve_package kwargs whose digests all match each other."""
    contract = _load_contract()
    registry = {
        "kind": "icp-p1a-registries", "schema_version": 1,
        "task_sources": ["csv"], "design_sources": ["lanhu-figma"],
        "platforms": {
            platform_id: {
                "profiles": [profile_id],
                "default_profile": profile_id,
                "activated": False,
            },
        },
        "operations": [{"id": "project_preflight"}],
        "capability_states": ["required"],
        "capabilities": {"project_preflight": "required"},
    }
    reg_digest = contract.compute_registry_digest(registry)
    sel_digest = contract.compute_selected_profile_digest(
        registry, platform_id, profile_id
    )
    if descriptor is None:
        descriptor = _synthetic_descriptor(
            platform_id=platform_id, profile_id=profile_id,
            registry_digest=reg_digest, selected_profile_digest=sel_digest,
        )
    if module_bytes is None:
        module_bytes = _synthetic_module_bytes()
    module_sha = _sha256_bytes(module_bytes)
    desc_digest = contract.compute_descriptor_digest(descriptor)
    if index_rows is None:
        index_rows = [
            _synthetic_index_row(
                platform_id=platform_id, profile_id=profile_id,
                module_sha=module_sha, descriptor_digest=desc_digest,
            )
        ]
    index = _synthetic_index(index_rows)
    return dict(
        platform_id=platform_id, profile_id=profile_id,
        registries=registry, package_index=index,
        package_descriptor=descriptor, package_module_bytes=module_bytes,
    )


def _make_resolution(**over) -> dict:
    base = {
        "kind": KIND_RESOLUTION, "schema_version": SCHEMA_VERSION,
        "platform_id": "synthetic", "profile_id": "synthetic-default",
        "package_module_basename": "synthetic_package_v1.py",
        "package_module_sha256": DIGEST_MODULE,
        "package_index_digest": DIGEST_INDEX,
        "package_descriptor_digest": DIGEST_DESCRIPTOR,
        "registry_digest": DIGEST_REGISTRY,
        "selected_profile_digest": DIGEST_SELECTED_PROFILE,
        "activation_state": ACTIVATION_STATE_INACTIVE,
        "executable": False,
    }
    base.update(over)
    return base


def _resolve_synthetic(resolver_module) -> dict:
    return resolver_module.resolve_package(
        **_resolve_synthetic_kwargs(resolver_module=resolver_module))


def _producer_script_bytes(*, with_drift: str | None = None) -> dict:
    bytes_by_id = {
        "entry-readiness-v1": b"// entry_readiness_v1.py bytes\n",
        "platform-package-resolver-v1":
            b"// platform_package_resolver_v1.py bytes\n",
        "freeze-platform-package-selection-v1":
            b"// freeze_platform_package_selection_v1.py bytes\n",
        "verify-platform-package-selection-v1":
            b"// verify_platform_package_selection_v1.py bytes\n",
    }
    if with_drift is not None:
        bytes_by_id[with_drift] = b"// TAMPERED\n"
    return bytes_by_id


def _build_selection_kwargs(
    *, resolver_module, freezer_module, resolution: dict | None = None,
    entry_readiness_report_digest: str = DIGEST_ENTRY_READINESS,
    selection_manifest_digest: str = DIGEST_SELECTION_MANIFEST,
    package_verification_digest: str = DIGEST_PACKAGE_VERIFICATION,
    producer_script_bytes: dict | None = None,
) -> dict:
    if resolution is None:
        resolution = _resolve_synthetic(resolver_module)
    if producer_script_bytes is None:
        producer_script_bytes = _producer_script_bytes()
    return dict(
        resolution=resolution,
        entry_readiness_report_digest=entry_readiness_report_digest,
        selection_manifest_digest=selection_manifest_digest,
        package_verification_digest=package_verification_digest,
        producer_script_bytes=producer_script_bytes,
    )


def _build_canonical_selection_and_kwargs(resolver, freezer) -> tuple:
    resolution = _resolve_synthetic(resolver)
    producer_bytes = _producer_script_bytes()
    selection = freezer.build_selection(
        resolution=resolution,
        entry_readiness_report_digest=DIGEST_ENTRY_READINESS,
        selection_manifest_digest=DIGEST_SELECTION_MANIFEST,
        package_verification_digest=DIGEST_PACKAGE_VERIFICATION,
        producer_script_bytes=producer_bytes,
    )
    return selection, dict(
        resolution=resolution,
        expected_entry_readiness_report_digest=DIGEST_ENTRY_READINESS,
        expected_selection_manifest_digest=DIGEST_SELECTION_MANIFEST,
        expected_package_verification_digest=DIGEST_PACKAGE_VERIFICATION,
        producer_script_bytes=producer_bytes,
    )


# ---------------------------------------------------------------------------
# 1. Module / index absence is RED before implementation.
# ---------------------------------------------------------------------------


def test_module_absence_red_then_present_green() -> None:
    """If any production module or the index is missing, loaders raise
    FileNotFoundError. Once present, all three modules import cleanly
    in a fresh subprocess with ``icp/scripts`` on ``PYTHONPATH``."""
    files_absent = (
        not RESOLVER_PATH.exists() or not FREEZER_PATH.exists()
        or not VERIFIER_PATH.exists() or not INDEX_PATH.exists()
    )
    if files_absent:
        _expect_reject(_load_resolver, "resolver absence should raise")
        _expect_reject(_load_freezer, "freezer absence should raise")
        _expect_reject(_load_verifier, "verifier absence should raise")
        _expect_reject(_read_index, "index absence should raise")
        return
    resolver = _load_resolver()
    freezer = _load_freezer()
    verifier = _load_verifier()
    assert hasattr(resolver, "PlatformPackageResolverError")
    assert hasattr(freezer, "PlatformPackageSelectionBuildError")
    assert hasattr(verifier, "PlatformPackageSelectionVerificationError")
    code = (
        "import platform_package_resolver_v1 as r;"
        "import freeze_platform_package_selection_v1 as f;"
        "import verify_platform_package_selection_v1 as v;"
        "print('IMPORT_OK');"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
             "PYTHONPATH": str(ICP_SCRIPTS)},
    )
    assert result.returncode == 0, (
        f"fresh import failed: rc={result.returncode} stderr={result.stderr}"
    )
    assert result.stdout.strip() == "IMPORT_OK"


# ---------------------------------------------------------------------------
# 2. Closed public API for all three modules.
# ---------------------------------------------------------------------------


def _assert_no_public_constants(path: Path, label: str) -> None:
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (isinstance(target, ast.Name)
                        and not target.id.startswith("_")):
                    raise AssertionError(
                        f"{label}: public constant: {target.id}"
                    )
        elif isinstance(node, ast.AnnAssign):
            if (isinstance(node.target, ast.Name)
                    and not node.target.id.startswith("_")):
                raise AssertionError(
                    f"{label}: public constant: {node.target.id}"
                )


def test_resolver_public_api_closed() -> None:
    import inspect
    mod = _load_resolver()
    expected_funcs = {
        "document_digest", "verify_package_index", "verify_resolution",
        "resolve_package",
    }
    funcs = {
        n for n in dir(mod)
        if not n.startswith("_") and inspect.isfunction(getattr(mod, n))
        and getattr(mod, n).__module__ == mod.__name__
    }
    assert funcs == expected_funcs, (
        f"resolver funcs: extra={sorted(funcs - expected_funcs)} "
        f"missing={sorted(expected_funcs - funcs)}"
    )
    classes = {
        n for n in dir(mod)
        if not n.startswith("_") and inspect.isclass(getattr(mod, n))
        and getattr(mod, n).__module__ == mod.__name__
    }
    assert classes == {"PlatformPackageResolverError"}
    _assert_no_public_constants(RESOLVER_PATH, "resolver")
    sig = inspect.signature(mod.resolve_package)
    params = list(sig.parameters.values())
    assert all(p.kind == p.KEYWORD_ONLY for p in params), sig
    assert {p.name for p in params} == {
        "platform_id", "profile_id", "registries", "package_index",
        "package_descriptor", "package_module_bytes",
    }, sig


def test_freezer_public_api_closed() -> None:
    import inspect
    mod = _load_freezer()
    expected_funcs = {"canonical_bytes", "build_selection"}
    funcs = {
        n for n in dir(mod)
        if not n.startswith("_") and inspect.isfunction(getattr(mod, n))
        and getattr(mod, n).__module__ == mod.__name__
    }
    assert funcs == expected_funcs
    classes = {
        n for n in dir(mod)
        if not n.startswith("_") and inspect.isclass(getattr(mod, n))
        and getattr(mod, n).__module__ == mod.__name__
    }
    assert classes == {"PlatformPackageSelectionBuildError"}
    _assert_no_public_constants(FREEZER_PATH, "freezer")
    sig = inspect.signature(mod.build_selection)
    params = list(sig.parameters.values())
    assert all(p.kind == p.KEYWORD_ONLY for p in params), sig
    assert {p.name for p in params} == {
        "resolution", "entry_readiness_report_digest",
        "selection_manifest_digest", "package_verification_digest",
        "producer_script_bytes",
    }, sig


def test_verifier_public_api_closed() -> None:
    import inspect
    mod = _load_verifier()
    expected_funcs = {"document_digest", "verify_selection"}
    funcs = {
        n for n in dir(mod)
        if not n.startswith("_") and inspect.isfunction(getattr(mod, n))
        and getattr(mod, n).__module__ == mod.__name__
    }
    assert funcs == expected_funcs
    classes = {
        n for n in dir(mod)
        if not n.startswith("_") and inspect.isclass(getattr(mod, n))
        and getattr(mod, n).__module__ == mod.__name__
    }
    assert classes == {"PlatformPackageSelectionVerificationError"}
    _assert_no_public_constants(VERIFIER_PATH, "verifier")
    sig = inspect.signature(mod.verify_selection)
    params = list(sig.parameters.values())
    assert params[0].name == "document"
    for p in params[1:]:
        assert p.kind == p.KEYWORD_ONLY, p
    assert {p.name for p in params[1:]} == {
        "resolution", "expected_entry_readiness_report_digest",
        "expected_selection_manifest_digest",
        "expected_package_verification_digest", "producer_script_bytes",
    }, sig


# ---------------------------------------------------------------------------
# 3. document_digest / canonical_bytes canonical.
# ---------------------------------------------------------------------------


def test_resolver_and_verifier_document_digest_canonical() -> None:
    for mod in (_load_resolver(), _load_verifier()):
        sample = {"b": 1, "a": [1, 2], "c": "x"}
        expected = _sha256_bytes(_canonical_json_bytes(sample))
        assert mod.document_digest(sample) == expected
        assert mod.document_digest({"a": 1, "b": 2}) == \
            mod.document_digest({"b": 2, "a": 1})
        _expect_reject(
            lambda: mod.document_digest("not a dict"), "digest non-dict",
        )


def test_freezer_canonical_bytes_canonical() -> None:
    mod = _load_freezer()
    sample = {"b": 1, "a": [1, 2], "c": "x"}
    expected = _canonical_json_bytes(sample)
    assert mod.canonical_bytes(sample) == expected
    assert mod.canonical_bytes({"a": 1, "b": 2}) == \
        mod.canonical_bytes({"b": 2, "a": 1})
    _expect_reject(
        lambda: mod.canonical_bytes("not a dict"), "canonical_bytes non-dict",
    )


# ---------------------------------------------------------------------------
# 4. verify_package_index accepts / rejects.
# ---------------------------------------------------------------------------


def test_verify_package_index_accepts_synthetic_non_flutter() -> None:
    mod = _load_resolver()
    rows = [
        _synthetic_index_row(platform_id="alpha", profile_id="alpha-default"),
        _synthetic_index_row(
            platform_id="beta", profile_id="beta-default",
            basename="beta_package_v1.py",
        ),
    ]
    mod.verify_package_index(_synthetic_index(rows))


def test_verify_package_index_rejects_shape_and_value_violations() -> None:
    mod = _load_resolver()
    base = _synthetic_index()
    bad_cases: list[tuple[str, dict]] = [
        ("reordered", _reordered(base, INDEX_KEYS)),
        ("unknown_top", {**base, "extra": "x"}),
        ("bad_kind", {**base, "kind": "icp.something.else.v1"}),
        ("bad_version", {**base, "schema_version": 2}),
        ("packages_not_list", {**base, "packages": "x"}),
        ("packages_empty", {**base, "packages": []}),
    ]
    for label, doc in bad_cases:
        _expect_reject(
            lambda d=doc: mod.verify_package_index(d),
            f"index accepts {label}",
        )
    row = _synthetic_index_row()
    bad_rows: list[tuple[str, dict]] = [
        ("row_reordered", _reordered(row, INDEX_ROW_KEYS)),
        ("row_unknown", {**row, "extra": "x"}),
    ]
    for label, bad_row in bad_rows:
        _expect_reject(
            lambda r=bad_row: mod.verify_package_index(_synthetic_index([r])),
            f"index accepts {label}",
        )
    # Missing required row key.
    for key in INDEX_ROW_KEYS:
        bad = {k: v for k, v in row.items() if k != key}
        _expect_reject(
            lambda r=bad, k=key: mod.verify_package_index(
                _synthetic_index([r])
            ),
            f"index accepts row missing {key}",
        )
    # Bad platform / profile IDs.
    for bad_id in (
        "", "UPPER", "has space", "has/slash", "has\\back",
        "x" * 129, "has:colon", "has,comma",
    ):
        bad_row = {**row, "platform_id": bad_id}
        _expect_reject(
            lambda r=bad_row: mod.verify_package_index(_synthetic_index([r])),
            f"index accepts bad platform_id {bad_id!r}",
        )
    # Bad basenames.
    for bad_base in (
        "noext", "foo.txt", "foo/bar.py", "foo\\bar.py",
        "/abs/path.py", ".", "..", "", "x\0y.py",
    ):
        bad_row = {**row, "package_module_basename": bad_base}
        _expect_reject(
            lambda r=bad_row: mod.verify_package_index(_synthetic_index([r])),
            f"index accepts bad basename {bad_base!r}",
        )
    # Bad SHA / digest values.
    for bad_dig in ("", "x" * 30, "X" * 64, "g" * 64, "ab", None, 1):
        bad_row = {**row, "package_module_sha256": bad_dig}
        _expect_reject(
            lambda r=bad_row: mod.verify_package_index(_synthetic_index([r])),
            f"index accepts bad module_sha {bad_dig!r}",
        )


def test_verify_package_index_rejects_sorting_dup() -> None:
    mod = _load_resolver()
    base_row = _synthetic_index_row()
    dup = _synthetic_index([base_row, dict(base_row)])
    _expect_reject(lambda: mod.verify_package_index(dup), "duplicate rows")
    row_a = _synthetic_index_row(platform_id="zzz", profile_id="p")
    row_b = _synthetic_index_row(platform_id="aaa", profile_id="p")
    unsorted = _synthetic_index([row_a, row_b])
    _expect_reject(lambda: mod.verify_package_index(unsorted), "unsorted")
    row_a2 = _synthetic_index_row(
        platform_id="same", profile_id="prof", basename="a_package_v1.py",
    )
    row_b2 = _synthetic_index_row(
        platform_id="same", profile_id="prof", basename="b_package_v1.py",
    )
    _expect_reject(
        lambda: mod.verify_package_index(_synthetic_index([row_a2, row_b2])),
        "duplicate key different rows",
    )
    # Strictly-sorted unique rows (different platform_id) accepted.
    sorted_unique = _synthetic_index(sorted(
        [_synthetic_index_row(platform_id="aaa", profile_id="p1"),
         _synthetic_index_row(platform_id="bbb", profile_id="p2")],
        key=lambda r: (r["platform_id"], r["profile_id"]),
    ))
    mod.verify_package_index(sorted_unique)


def test_verify_package_index_rejects_injection_keys_recursive() -> None:
    mod = _load_resolver()
    base = _synthetic_index()
    for key in INJECTION_FIELDS:
        bad = {**base, key: "x"}
        _expect_reject(
            lambda d=bad, k=key: mod.verify_package_index(d),
            f"index top injection {key}",
        )
        bad_row = {**_synthetic_index_row(), key: "x"}
        bad = _synthetic_index([bad_row])
        _expect_reject(
            lambda d=bad, k=key: mod.verify_package_index(d),
            f"index row injection {key}",
        )


# ---------------------------------------------------------------------------
# 5. verify_resolution accepts / rejects.
# ---------------------------------------------------------------------------


def test_verify_resolution_accepts_valid() -> None:
    _load_resolver().verify_resolution(_make_resolution())


def test_verify_resolution_rejects_shape_and_value_violations() -> None:
    mod = _load_resolver()
    base = _make_resolution()
    bad_cases: list[tuple[str, dict]] = [
        ("reordered", _reordered(base, RESOLUTION_KEYS)),
        ("unknown", {**base, "extra": "x"}),
        ("bad_kind", {**base, "kind": "icp.something.else.v1"}),
        ("bad_version", {**base, "schema_version": 2}),
        ("bad_platform", {**base, "platform_id": "UPPER"}),
        ("bad_profile", {**base, "profile_id": "has space"}),
        ("bad_basename", {**base, "package_module_basename": "foo.txt"}),
        ("bad_basename_slash", {
            **base, "package_module_basename": "a/b.py",
        }),
        ("bad_module_sha", {**base, "package_module_sha256": "X" * 64}),
        ("bad_index_digest", {**base, "package_index_digest": "g" * 64}),
        ("bad_descriptor_digest", {
            **base, "package_descriptor_digest": "ab",
        }),
        ("bad_registry_digest", {**base, "registry_digest": "x" * 30}),
        ("bad_selected_profile_digest", {
            **base, "selected_profile_digest": None,
        }),
        ("active", {**base, "activation_state": "active"}),
        ("executable_true", {**base, "executable": True}),
    ]
    for label, doc in bad_cases:
        _expect_reject(
            lambda d=doc: mod.verify_resolution(d),
            f"resolution accepts {label}",
        )
    for key in RESOLUTION_KEYS:
        bad = {k: v for k, v in base.items() if k != key}
        _expect_reject(
            lambda d=bad, k=key: mod.verify_resolution(d),
            f"resolution accepts missing {key}",
        )


def test_verify_resolution_rejects_injection_keys_recursive() -> None:
    mod = _load_resolver()
    base = _make_resolution()
    for key in INJECTION_FIELDS:
        bad = {**base, key: "x"}
        _expect_reject(
            lambda d=bad, k=key: mod.verify_resolution(d),
            f"resolution accepts injection {key}",
        )


# ---------------------------------------------------------------------------
# 6. resolve_package: happy paths + drift / mismatch / activation reject.
# ---------------------------------------------------------------------------


def test_resolve_package_synthetic_non_flutter_happy_path() -> None:
    resolver = _load_resolver()
    contract = _load_contract()
    kwargs = _resolve_synthetic_kwargs(resolver_module=resolver)
    resolution = resolver.resolve_package(**kwargs)
    assert tuple(resolution.keys()) == RESOLUTION_KEYS
    assert resolution["kind"] == KIND_RESOLUTION
    assert resolution["schema_version"] == SCHEMA_VERSION
    assert resolution["activation_state"] == ACTIVATION_STATE_INACTIVE
    assert resolution["executable"] is False
    assert resolution["package_module_sha256"] == \
        _sha256_bytes(kwargs["package_module_bytes"])
    assert resolution["package_descriptor_digest"] == \
        contract.compute_descriptor_digest(kwargs["package_descriptor"])
    assert resolution["package_index_digest"] == \
        resolver.document_digest(kwargs["package_index"])
    assert resolution["registry_digest"] == \
        contract.compute_registry_digest(kwargs["registries"])
    assert resolution["selected_profile_digest"] == \
        contract.compute_selected_profile_digest(
            kwargs["registries"], kwargs["platform_id"],
            kwargs["profile_id"],
        )


def test_resolve_package_flutter_live_happy_path() -> None:
    resolver = _load_resolver()
    contract = _load_contract()
    flutter = _load_flutter_package()
    descriptor = flutter.describe_package()
    module_bytes = FLUTTER_PACKAGE_PATH.read_bytes()
    module_sha = _sha256_bytes(module_bytes)
    descriptor_digest = contract.compute_descriptor_digest(descriptor)
    index = _synthetic_index([{
        "platform_id": "flutter", "profile_id": "flutter-standard",
        "package_module_basename": "flutter_package_v1.py",
        "package_module_sha256": module_sha,
        "package_descriptor_digest": descriptor_digest,
    }])
    registries = _read_registry()
    resolution = resolver.resolve_package(
        platform_id="flutter", profile_id="flutter-standard",
        registries=registries, package_index=index,
        package_descriptor=descriptor, package_module_bytes=module_bytes,
    )
    assert resolution["platform_id"] == "flutter"
    assert resolution["profile_id"] == "flutter-standard"
    assert resolution["package_module_basename"] == "flutter_package_v1.py"
    assert resolution["package_module_sha256"] == module_sha
    assert resolution["package_descriptor_digest"] == descriptor_digest
    assert resolution["package_index_digest"] == \
        resolver.document_digest(index)
    assert resolution["registry_digest"] == \
        contract.compute_registry_digest(registries)
    assert resolution["selected_profile_digest"] == \
        contract.compute_selected_profile_digest(
            registries, "flutter", "flutter-standard"
        )
    assert resolution["activation_state"] == "active"
    assert resolution["executable"] is True


def test_resolve_package_rejects_unknown_platform_profile() -> None:
    resolver = _load_resolver()
    base_kwargs = _resolve_synthetic_kwargs(resolver_module=resolver)
    other_row = _synthetic_index_row(
        platform_id="zzz-other", profile_id="zzz-default",
    )
    base_kwargs["package_index"]["packages"].append(other_row)
    base_kwargs["package_index"]["packages"].sort(
        key=lambda r: (r["platform_id"], r["profile_id"])
    )
    _expect_reject(
        lambda: resolver.resolve_package(**{
            **base_kwargs, "platform_id": "missing",
            "profile_id": "missing-default",
        }),
        "resolve accepts unknown platform",
    )


def test_resolve_package_rejects_duplicate_index_row() -> None:
    resolver = _load_resolver()
    base_kwargs = _resolve_synthetic_kwargs(resolver_module=resolver)
    dup_row = dict(base_kwargs["package_index"]["packages"][0])
    base_kwargs["package_index"]["packages"].append(dup_row)
    _expect_reject(
        lambda: resolver.resolve_package(**base_kwargs),
        "resolve accepts duplicate index row",
    )


def test_resolve_package_rejects_descriptor_platform_profile_mismatch() -> None:
    resolver = _load_resolver()
    contract = _load_contract()
    base_kwargs = _resolve_synthetic_kwargs(resolver_module=resolver)
    bad_descriptor = dict(base_kwargs["package_descriptor"])
    bad_descriptor["platform_id"] = "other-platform"
    new_desc_digest = contract.compute_descriptor_digest(bad_descriptor)
    base_kwargs["package_index"]["packages"][0][
        "package_descriptor_digest"
    ] = new_desc_digest
    _expect_reject(
        lambda: resolver.resolve_package(
            **{**base_kwargs, "package_descriptor": bad_descriptor}
        ),
        "resolve accepts descriptor platform mismatch",
    )


def test_resolve_package_rejects_module_bytes_drift() -> None:
    resolver = _load_resolver()
    base_kwargs = _resolve_synthetic_kwargs(resolver_module=resolver)
    _expect_reject(
        lambda: resolver.resolve_package(
            **{**base_kwargs, "package_module_bytes": b"# tampered\n"}
        ),
        "resolve accepts module bytes drift",
    )


def test_resolve_package_rejects_descriptor_digest_drift() -> None:
    resolver = _load_resolver()
    base_kwargs = _resolve_synthetic_kwargs(resolver_module=resolver)
    base_kwargs["package_index"]["packages"][0][
        "package_descriptor_digest"
    ] = DIGEST_ALT
    _expect_reject(
        lambda: resolver.resolve_package(**base_kwargs),
        "resolve accepts descriptor digest drift",
    )


def test_resolve_package_rejects_registry_or_selected_profile_digest_drift() -> None:
    resolver = _load_resolver()
    contract = _load_contract()
    base_kwargs = _resolve_synthetic_kwargs(resolver_module=resolver)
    bad_descriptor = dict(base_kwargs["package_descriptor"])
    bad_descriptor["registry_digest"] = DIGEST_ALT
    new_desc_digest = contract.compute_descriptor_digest(bad_descriptor)
    base_kwargs["package_index"]["packages"][0][
        "package_descriptor_digest"
    ] = new_desc_digest
    _expect_reject(
        lambda: resolver.resolve_package(
            **{**base_kwargs, "package_descriptor": bad_descriptor}
        ),
        "resolve accepts registry digest drift",
    )
    base_kwargs2 = _resolve_synthetic_kwargs(resolver_module=resolver)
    bad_descriptor2 = dict(base_kwargs2["package_descriptor"])
    bad_descriptor2["selected_profile_digest"] = DIGEST_ALT
    new_desc_digest2 = contract.compute_descriptor_digest(bad_descriptor2)
    base_kwargs2["package_index"]["packages"][0][
        "package_descriptor_digest"
    ] = new_desc_digest2
    _expect_reject(
        lambda: resolver.resolve_package(
            **{**base_kwargs2, "package_descriptor": bad_descriptor2}
        ),
        "resolve accepts selected-profile digest drift",
    )


def test_resolve_package_rejects_active_or_executable_descriptor() -> None:
    resolver = _load_resolver()
    contract = _load_contract()
    base_kwargs = _resolve_synthetic_kwargs(resolver_module=resolver)
    bad_descriptor = dict(base_kwargs["package_descriptor"])
    bad_descriptor["activation_state"] = "active"
    new_desc_digest = contract.compute_descriptor_digest(bad_descriptor)
    base_kwargs["package_index"]["packages"][0][
        "package_descriptor_digest"
    ] = new_desc_digest
    _expect_reject(
        lambda: resolver.resolve_package(
            **{**base_kwargs, "package_descriptor": bad_descriptor}
        ),
        "resolve accepts active descriptor",
    )
    base_kwargs2 = _resolve_synthetic_kwargs(resolver_module=resolver)
    bad_descriptor2 = dict(base_kwargs2["package_descriptor"])
    bad_descriptor2["executable"] = True
    new_desc_digest2 = contract.compute_descriptor_digest(bad_descriptor2)
    base_kwargs2["package_index"]["packages"][0][
        "package_descriptor_digest"
    ] = new_desc_digest2
    _expect_reject(
        lambda: resolver.resolve_package(
            **{**base_kwargs2, "package_descriptor": bad_descriptor2}
        ),
        "resolve accepts executable descriptor",
    )


def test_resolve_package_rejects_invalid_inputs() -> None:
    resolver = _load_resolver()
    base_kwargs = _resolve_synthetic_kwargs(resolver_module=resolver)
    _expect_reject(
        lambda: resolver.resolve_package(
            **{**base_kwargs, "package_module_bytes": "not bytes"}
        ),
        "resolve accepts str module bytes",
    )
    # bytearray is bytes-like and allowed.
    resolver.resolve_package(
        **{**base_kwargs,
           "package_module_bytes": bytearray(base_kwargs["package_module_bytes"])}
    )
    _expect_reject(
        lambda: resolver.resolve_package(
            **{**base_kwargs, "platform_id": "UPPER"}
        ),
        "resolve accepts unsafe platform_id",
    )
    _expect_reject(
        lambda: resolver.resolve_package(
            **{**base_kwargs, "profile_id": "has space"}
        ),
        "resolve accepts unsafe profile_id",
    )
    _expect_reject(
        lambda: resolver.resolve_package(
            **{**base_kwargs, "registries": "not a dict"}
        ),
        "resolve accepts bad registries type",
    )


def test_resolve_package_rejects_injection_in_descriptor_or_index() -> None:
    resolver = _load_resolver()
    base_kwargs = _resolve_synthetic_kwargs(resolver_module=resolver)
    bad_descriptor = copy.deepcopy(base_kwargs["package_descriptor"])
    bad_descriptor["entry_requirements"].append({
        "id": "x", "owner": "user", "required": True, "sensitive": False,
        "probe_id": "x", "accepted_shape_id": "x",
        "remediation_id": "x", "command": "pwned",
    })
    _expect_reject(
        lambda: resolver.resolve_package(
            **{**base_kwargs, "package_descriptor": bad_descriptor}
        ),
        "resolve accepts injection in descriptor",
    )
    bad_index = copy.deepcopy(base_kwargs["package_index"])
    bad_index["packages"][0]["command"] = "pwned"
    _expect_reject(
        lambda: resolver.resolve_package(
            **{**base_kwargs, "package_index": bad_index}
        ),
        "resolve accepts injection in index",
    )


# ---------------------------------------------------------------------------
# 7. build_selection: happy path + exact keys + producer rules.
# ---------------------------------------------------------------------------


def test_build_selection_happy_path_and_exact_keys() -> None:
    resolver = _load_resolver()
    freezer = _load_freezer()
    selection = freezer.build_selection(**_build_selection_kwargs(
        resolver_module=resolver, freezer_module=freezer,
    ))
    assert tuple(selection.keys()) == SELECTION_KEYS
    assert selection["kind"] == KIND_SELECTION
    assert selection["schema_version"] == SCHEMA_VERSION
    assert selection["activation_state"] == ACTIVATION_STATE_INACTIVE
    assert selection["executable"] is False
    assert isinstance(selection["producer_script_digests"], list)
    assert len(selection["producer_script_digests"]) == len(PRODUCER_SPECS)


def test_build_selection_producer_ids_order_and_basenames_fixed() -> None:
    resolver = _load_resolver()
    freezer = _load_freezer()
    selection = freezer.build_selection(**_build_selection_kwargs(
        resolver_module=resolver, freezer_module=freezer,
    ))
    producers = selection["producer_script_digests"]
    for i, (pid, basename) in enumerate(PRODUCER_SPECS):
        row = producers[i]
        assert tuple(row.keys()) == PRODUCER_ROW_KEYS, (
            f"producer[{i}] keys: {tuple(row.keys())}"
        )
        assert row["id"] == pid
        assert row["basename"] == basename
        assert isinstance(row["sha256"], str) and len(row["sha256"]) == 64


def test_build_selection_rejects_producer_script_bytes_violations() -> None:
    resolver = _load_resolver()
    freezer = _load_freezer()
    base_kwargs = _build_selection_kwargs(
        resolver_module=resolver, freezer_module=freezer,
    )
    missing = dict(base_kwargs["producer_script_bytes"])
    del missing[PRODUCER_IDS[0]]
    _expect_reject(
        lambda: freezer.build_selection(
            **{**base_kwargs, "producer_script_bytes": missing}
        ),
        "build accepts missing producer",
    )
    extra = dict(base_kwargs["producer_script_bytes"])
    extra["unknown-id"] = b"x"
    _expect_reject(
        lambda: freezer.build_selection(
            **{**base_kwargs, "producer_script_bytes": extra}
        ),
        "build accepts extra producer",
    )
    inj = dict(base_kwargs["producer_script_bytes"])
    inj["command"] = b"x"
    _expect_reject(
        lambda: freezer.build_selection(
            **{**base_kwargs, "producer_script_bytes": inj}
        ),
        "build accepts injection producer id",
    )
    bad_type = dict(base_kwargs["producer_script_bytes"])
    bad_type[PRODUCER_IDS[1]] = "not bytes"
    _expect_reject(
        lambda: freezer.build_selection(
            **{**base_kwargs, "producer_script_bytes": bad_type}
        ),
        "build accepts str producer bytes",
    )
    _expect_reject(
        lambda: freezer.build_selection(
            **{**base_kwargs, "producer_script_bytes": ["a", "b"]}
        ),
        "build accepts list producer_script_bytes",
    )


def test_build_selection_rejects_invalid_adjacent_digests() -> None:
    resolver = _load_resolver()
    freezer = _load_freezer()
    base_kwargs = _build_selection_kwargs(
        resolver_module=resolver, freezer_module=freezer,
    )
    for bad_dig in ("", "x" * 30, "X" * 64, "g" * 64, None, 1):
        _expect_reject(
            lambda b=bad_dig: freezer.build_selection(
                **{**base_kwargs,
                   "entry_readiness_report_digest": b}
            ),
            f"build accepts bad entry_readiness {bad_dig!r}",
        )
        _expect_reject(
            lambda b=bad_dig: freezer.build_selection(
                **{**base_kwargs,
                   "selection_manifest_digest": b}
            ),
            f"build accepts bad manifest {bad_dig!r}",
        )
        _expect_reject(
            lambda b=bad_dig: freezer.build_selection(
                **{**base_kwargs,
                   "package_verification_digest": b}
            ),
            f"build accepts bad pkg_verify {bad_dig!r}",
        )


def test_build_selection_rejects_unverified_resolution() -> None:
    resolver = _load_resolver()
    freezer = _load_freezer()
    base_kwargs = _build_selection_kwargs(
        resolver_module=resolver, freezer_module=freezer,
    )
    for over in (
        {"activation_state": "active"},
        {"executable": True},
        {"kind": "icp.something.else.v1"},
    ):
        bad_resolution = dict(base_kwargs["resolution"], **over)
        _expect_reject(
            lambda r=bad_resolution, o=over: freezer.build_selection(
                **{**base_kwargs, "resolution": r}
            ),
            f"build accepts resolution {over}",
        )


def test_build_selection_output_has_no_injection_keys() -> None:
    resolver = _load_resolver()
    freezer = _load_freezer()
    selection = freezer.build_selection(**_build_selection_kwargs(
        resolver_module=resolver, freezer_module=freezer,
    ))
    seen = []

    def walk(obj):
        if isinstance(obj, dict):
            seen.extend(obj.keys())
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
    walk(selection)
    for key in seen:
        assert key not in INJECTION_FIELDS, (
            f"selection output contains injection key: {key!r}"
        )


# ---------------------------------------------------------------------------
# 8. verify_selection: happy path + tamper / drift / injection rejections.
# ---------------------------------------------------------------------------


def test_verifier_verify_selection_happy_path() -> None:
    resolver = _load_resolver()
    freezer = _load_freezer()
    verifier = _load_verifier()
    selection, kwargs = _build_canonical_selection_and_kwargs(
        resolver, freezer
    )
    verification = verifier.verify_selection(selection, **kwargs)
    assert tuple(verification.keys()) == VERIFICATION_KEYS
    assert verification["kind"] == KIND_VERIFICATION
    assert verification["schema_version"] == SCHEMA_VERSION
    assert verification["platform_id"] == selection["platform_id"]
    assert verification["profile_id"] == selection["profile_id"]
    assert verification["verified"] is True
    assert verification["selection_digest"] == \
        verifier.document_digest(selection)


def test_verifier_verify_selection_rejects_shape_violations() -> None:
    resolver = _load_resolver()
    freezer = _load_freezer()
    verifier = _load_verifier()
    selection, kwargs = _build_canonical_selection_and_kwargs(
        resolver, freezer
    )
    bad_cases: list[tuple[str, dict]] = [
        ("reordered", _reordered(selection, SELECTION_KEYS)),
        ("unknown", {**selection, "extra": "x"}),
        ("bad_kind", {**selection, "kind": "icp.something.else.v1"}),
        ("bad_version", {**selection, "schema_version": 2}),
        ("active", {**selection, "activation_state": "active"}),
        ("executable_true", {**selection, "executable": True}),
    ]
    for label, doc in bad_cases:
        _expect_reject(
            lambda d=doc, kw=kwargs: verifier.verify_selection(d, **kw),
            f"verify accepts {label}",
        )
    for key in SELECTION_KEYS:
        bad = {k: v for k, v in selection.items() if k != key}
        _expect_reject(
            lambda d=bad, k=key, kw=kwargs: verifier.verify_selection(
                d, **kw
            ),
            f"verify accepts missing {key}",
        )


def test_verifier_verify_selection_rejects_copied_field_tamper() -> None:
    resolver = _load_resolver()
    freezer = _load_freezer()
    verifier = _load_verifier()
    selection, kwargs = _build_canonical_selection_and_kwargs(
        resolver, freezer
    )
    for key in (
        "platform_id", "profile_id", "package_index_digest",
        "package_descriptor_digest", "registry_digest",
        "selected_profile_digest", "package_module_basename",
        "package_module_sha256",
    ):
        cur = selection[key]
        if key.endswith("_digest") or key == "package_module_sha256":
            new_val = ("9" if cur[0] != "9" else "8") + cur[1:]
        else:
            new_val = cur + "-tampered"
        bad = dict(selection)
        bad[key] = new_val
        _expect_reject(
            lambda d=bad, k=key, kw=kwargs: verifier.verify_selection(
                d, **kw
            ),
            f"verify accepts tampered copied field {key}",
        )


def test_verifier_verify_selection_rejects_active_executable_tamper() -> None:
    resolver = _load_resolver()
    freezer = _load_freezer()
    verifier = _load_verifier()
    selection, kwargs = _build_canonical_selection_and_kwargs(
        resolver, freezer
    )
    for over in ({"activation_state": "active"}, {"executable": True}):
        bad = dict(selection, **over)
        _expect_reject(
            lambda d=bad, o=over, kw=kwargs: verifier.verify_selection(
                d, **kw
            ),
            f"verify accepts tamper {over}",
        )


def test_verifier_verify_selection_rejects_producer_drift_or_tamper() -> None:
    resolver = _load_resolver()
    freezer = _load_freezer()
    verifier = _load_verifier()
    selection, kwargs = _build_canonical_selection_and_kwargs(
        resolver, freezer
    )
    drifted_bytes = _producer_script_bytes(with_drift=PRODUCER_IDS[0])
    _expect_reject(
        lambda: verifier.verify_selection(
            selection, **{**kwargs, "producer_script_bytes": drifted_bytes}
        ),
        "verify accepts producer digest drift",
    )
    for over, label in (
        ({"sha256": "0" * 64}, "sha tamper"),
        ({"id": "tampered-id"}, "id tamper"),
        ({"basename": "tampered.py"}, "basename tamper"),
        ({"extra": "x"}, "extra field"),
    ):
        bad = copy.deepcopy(selection)
        bad["producer_script_digests"][0] = dict(
            bad["producer_script_digests"][0], **over
        )
        _expect_reject(
            lambda d=bad, l=label, kw=kwargs: verifier.verify_selection(
                d, **kw
            ),
            f"verify accepts producer {label}",
        )


def test_verifier_verify_selection_rejects_producer_extra_missing_reorder() -> None:
    resolver = _load_resolver()
    freezer = _load_freezer()
    verifier = _load_verifier()
    selection, kwargs = _build_canonical_selection_and_kwargs(
        resolver, freezer
    )
    bad_extra = copy.deepcopy(selection)
    bad_extra["producer_script_digests"].append({
        "id": "extra-id", "basename": "x.py", "sha256": "0" * 64,
    })
    _expect_reject(
        lambda: verifier.verify_selection(bad_extra, **kwargs),
        "verify accepts extra producer row",
    )
    bad_missing = copy.deepcopy(selection)
    bad_missing["producer_script_digests"].pop()
    _expect_reject(
        lambda: verifier.verify_selection(bad_missing, **kwargs),
        "verify accepts missing producer row",
    )
    bad_reorder = copy.deepcopy(selection)
    bad_reorder["producer_script_digests"] = list(
        reversed(bad_reorder["producer_script_digests"])
    )
    _expect_reject(
        lambda: verifier.verify_selection(bad_reorder, **kwargs),
        "verify accepts reordered producer rows",
    )
    missing = dict(kwargs["producer_script_bytes"])
    del missing[PRODUCER_IDS[0]]
    _expect_reject(
        lambda: verifier.verify_selection(
            selection, **{**kwargs, "producer_script_bytes": missing}
        ),
        "verify accepts producer_script_bytes missing",
    )
    extra = dict(kwargs["producer_script_bytes"])
    extra["unknown-id"] = b"x"
    _expect_reject(
        lambda: verifier.verify_selection(
            selection, **{**kwargs, "producer_script_bytes": extra}
        ),
        "verify accepts producer_script_bytes extra",
    )


def test_verifier_verify_selection_rejects_adjacent_digest_drift() -> None:
    resolver = _load_resolver()
    freezer = _load_freezer()
    verifier = _load_verifier()
    selection, kwargs = _build_canonical_selection_and_kwargs(
        resolver, freezer
    )
    for key in (
        "expected_entry_readiness_report_digest",
        "expected_selection_manifest_digest",
        "expected_package_verification_digest",
    ):
        _expect_reject(
            lambda k=key: verifier.verify_selection(
                selection, **{**kwargs, k: DIGEST_ALT}
            ),
            f"verify accepts adjacent drift {key}",
        )
    bad = dict(selection)
    bad["entry_readiness_report_digest"] = DIGEST_ALT
    _expect_reject(
        lambda: verifier.verify_selection(bad, **kwargs),
        "verify accepts tampered entry_readiness",
    )


def test_verifier_verify_selection_rejects_unverified_resolution() -> None:
    resolver = _load_resolver()
    freezer = _load_freezer()
    verifier = _load_verifier()
    selection, kwargs = _build_canonical_selection_and_kwargs(
        resolver, freezer
    )
    bad_resolution = dict(kwargs["resolution"], activation_state="active")
    _expect_reject(
        lambda: verifier.verify_selection(
            selection, **{**kwargs, "resolution": bad_resolution}
        ),
        "verify accepts unverified resolution",
    )


def test_verifier_verify_selection_rejects_injection_keys_recursive() -> None:
    resolver = _load_resolver()
    freezer = _load_freezer()
    verifier = _load_verifier()
    selection, kwargs = _build_canonical_selection_and_kwargs(
        resolver, freezer
    )
    for key in INJECTION_FIELDS:
        bad = {**selection, key: "x"}
        _expect_reject(
            lambda d=bad, k=key, kw=kwargs: verifier.verify_selection(
                d, **kw
            ),
            f"verify accepts injection {key}",
        )
        bad2 = copy.deepcopy(selection)
        bad2["producer_script_digests"][0][key] = "x"
        _expect_reject(
            lambda d=bad2, k=key, kw=kwargs: verifier.verify_selection(
                d, **kw
            ),
            f"verify accepts nested injection {key}",
        )


# ---------------------------------------------------------------------------
# 9. Injection rejection is exact-key, not substring scan.
# ---------------------------------------------------------------------------


def test_injection_rejection_is_exact_key_no_substring_false_positive() -> None:
    """A legitimate controlled value containing a forbidden substring
    as part of a different identifier must NOT be rejected. Only exact
    dictionary key matches fail."""
    resolver = _load_resolver()
    base_kwargs = _resolve_synthetic_kwargs(resolver_module=resolver)
    descriptor = copy.deepcopy(base_kwargs["package_descriptor"])
    descriptor["entry_requirements"] = [{
        "id": LEGIT_VALUE_WITH_SUBSTRING,
        "owner": "user", "required": True, "sensitive": False,
        "probe_id": LEGIT_VALUE_WITH_SUBSTRING,
        "accepted_shape_id": "shape.legit",
        "remediation_id": "remediation.legit",
    }]
    contract = _load_contract()
    descriptor_digest = contract.compute_descriptor_digest(descriptor)
    base_kwargs["package_descriptor"] = descriptor
    base_kwargs["package_index"]["packages"][0][
        "package_descriptor_digest"
    ] = descriptor_digest
    resolution = resolver.resolve_package(**base_kwargs)
    assert resolution["activation_state"] == ACTIVATION_STATE_INACTIVE


# ---------------------------------------------------------------------------
# 10. Determinism + non-mutation across all three modules.
# ---------------------------------------------------------------------------


def test_determinism_and_input_immutability_resolver() -> None:
    resolver = _load_resolver()
    kwargs = _resolve_synthetic_kwargs(resolver_module=resolver)
    snap = copy.deepcopy(kwargs)
    r1 = resolver.resolve_package(**kwargs)
    r2 = resolver.resolve_package(**kwargs)
    assert resolver.document_digest(r1) == resolver.document_digest(r2)
    assert kwargs == snap


def test_determinism_and_input_immutability_freezer() -> None:
    resolver = _load_resolver()
    freezer = _load_freezer()
    kwargs = _build_selection_kwargs(
        resolver_module=resolver, freezer_module=freezer,
    )
    snap = copy.deepcopy(kwargs)
    s1 = freezer.build_selection(**kwargs)
    s2 = freezer.build_selection(**kwargs)
    assert freezer.canonical_bytes(s1) == freezer.canonical_bytes(s2)
    assert kwargs == snap


def test_determinism_and_input_immutability_verifier() -> None:
    resolver = _load_resolver()
    freezer = _load_freezer()
    verifier = _load_verifier()
    selection, kwargs = _build_canonical_selection_and_kwargs(
        resolver, freezer
    )
    snap_sel = copy.deepcopy(selection)
    snap_kw = copy.deepcopy(kwargs)
    v1 = verifier.verify_selection(selection, **kwargs)
    v2 = verifier.verify_selection(selection, **kwargs)
    assert verifier.document_digest(v1) == verifier.document_digest(v2)
    assert selection == snap_sel
    assert kwargs == snap_kw


# ---------------------------------------------------------------------------
# 11. Live index contains exactly the Flutter row with live values.
# ---------------------------------------------------------------------------


def test_live_index_exactly_matches_current_package_activation_states() -> None:
    resolver = _load_resolver()
    contract = _load_contract()
    index = _read_index()
    assert tuple(index.keys()) == INDEX_KEYS
    assert index["kind"] == KIND_INDEX
    assert index["schema_version"] == SCHEMA_VERSION
    resolver.verify_package_index(index)
    registries = _read_registry()
    expected = (
        (
            "android-java", "android-java-standard", "android_java_package_v1.py",
            PLATFORMS_DIR / "android_java_package_v1.py",
            _load("p4_android_java_package", PLATFORMS_DIR / "android_java_package_v1.py"),
        ),
        (
            "android-kotlin", "android-kotlin-standard", "android_kotlin_package_v1.py",
            PLATFORMS_DIR / "android_kotlin_package_v1.py",
            _load("p4_android_kotlin_package", PLATFORMS_DIR / "android_kotlin_package_v1.py"),
        ),
        (
            "flutter", "flutter-standard", "flutter_package_v1.py",
            FLUTTER_PACKAGE_PATH, _load_flutter_package(),
        ),
        (
            "ios-objc", "ios-objc-standard", "ios_objc_package_v1.py",
            PLATFORMS_DIR / "ios_objc_package_v1.py",
            _load("p4_ios_objc_package", PLATFORMS_DIR / "ios_objc_package_v1.py"),
        ),
        (
            "ios-swift", "ios-swift-standard", "ios_swift_package_v1.py",
            PLATFORMS_DIR / "ios_swift_package_v1.py",
            _load("p4_ios_swift_package", PLATFORMS_DIR / "ios_swift_package_v1.py"),
        ),
        (
            "nextjs", "nextjs-standard", "nextjs_package_v1.py",
            PLATFORMS_DIR / "nextjs_package_v1.py",
            _load("p4_nextjs_package", PLATFORMS_DIR / "nextjs_package_v1.py"),
        ),
        (
            "vue", "vue-vite", "vue_package_v1.py",
            VUE_PACKAGE_PATH, _load_vue_package(),
        ),
    )
    assert len(index["packages"]) == len(expected)
    for row, (platform_id, profile_id, basename, path, package) in zip(
        index["packages"], expected, strict=True
    ):
        assert tuple(row.keys()) == INDEX_ROW_KEYS
        assert (row["platform_id"], row["profile_id"]) == (platform_id, profile_id)
        assert row["package_module_basename"] == basename
        module_bytes = path.read_bytes()
        assert row["package_module_sha256"] == _sha256_bytes(module_bytes)
        descriptor = package.describe_package()
        assert row["package_descriptor_digest"] == contract.compute_descriptor_digest(
            descriptor
        )
        resolution = resolver.resolve_package(
            platform_id=platform_id, profile_id=profile_id,
            registries=registries, package_index=index,
            package_descriptor=descriptor, package_module_bytes=module_bytes,
        )
        assert resolution["activation_state"] == descriptor["activation_state"]
        assert resolution["executable"] is descriptor["executable"]
        assert resolution["platform_id"] == platform_id
        assert resolution["profile_id"] == profile_id
        assert resolution["package_module_basename"] == basename


# ---------------------------------------------------------------------------
# 12. AST / source purity across all three production modules.
# ---------------------------------------------------------------------------


_ALLOWED_STDLIB = {"__future__", "hashlib", "json", "typing"}
_ALLOWED_LOCAL_MODULES = {
    "platform_package_resolver_v1",
    "freeze_platform_package_selection_v1",
    "verify_platform_package_selection_v1",
}
_ALLOWED_LOCAL_PARENT_PACKAGES = {"platforms"}
_FORBIDDEN_IMPORT_ROOTS = {"importlib", "pathlib", "sys", "os"}
_FORBIDDEN_DYNAMIC_NAMES = {
    "spec_from_file_location", "module_from_spec", "exec_module",
    "__import__", "eval", "exec", "compile",
}
_FORBIDDEN_TOP_NAME_CALLS = {
    "open", "system", "popen", "execv", "execve", "execl",
    "spawnv", "spawnve", "fork", "urlopen", "eval", "exec", "__import__",
}
_FORBIDDEN_TOP_ATTR_CALLS = {
    "open", "resolve", "stat", "lstat", "exists", "is_file", "is_dir",
    "is_symlink", "readlink", "iterdir", "glob", "rglob", "read_text",
    "read_bytes", "write_text", "write_bytes", "mkdir", "unlink",
    "replace", "rename", "touch", "chmod", "symlink_to", "hardlink_to",
}
_FORBIDDEN_TOP_ATTR_CHAINS = {
    "subprocess.run", "subprocess.call", "subprocess.check_call",
    "subprocess.check_output", "subprocess.Popen",
    "subprocess.getoutput", "subprocess.getstatusoutput",
    "os.system", "os.popen", "os.execv", "os.spawnv", "os.fork",
    "os.execve", "os.execl", "os.getenv", "os.environ",
    "urllib.request.urlopen", "urllib.urlopen", "socket.socket",
    "fcntl.flock", "msvcrt.locking",
}


def _imports_of(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None
            names.append(node.module)
    return names


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
    violations = []

    def check(node: ast.Call) -> None:
        f = node.func
        if isinstance(f, ast.Name) and f.id in _FORBIDDEN_TOP_NAME_CALLS:
            violations.append(f.id)
        elif isinstance(f, ast.Attribute):
            chain = _attr_chain(f)
            last = chain.rsplit(".", 1)[-1]
            if chain in _FORBIDDEN_TOP_ATTR_CHAINS:
                violations.append(chain)
            elif last in _FORBIDDEN_TOP_ATTR_CALLS:
                violations.append(chain)

    for stmt in tree.body:
        if isinstance(
            stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            continue
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call):
                check(node)
    return violations


def _all_dynamic_import_violations(tree: ast.Module) -> list:
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _FORBIDDEN_IMPORT_ROOTS:
                    violations.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None:
                root = node.module.split(".")[0]
                if root in _FORBIDDEN_IMPORT_ROOTS:
                    violations.append(f"from {node.module} import ...")
        elif isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                if f.id in _FORBIDDEN_DYNAMIC_NAMES:
                    violations.append(f"call name {f.id}")
                elif f.id == "Path":
                    violations.append("call Path(...)")
            elif isinstance(f, ast.Attribute):
                if f.attr in _FORBIDDEN_DYNAMIC_NAMES:
                    violations.append(f"attr .{f.attr}")
                elif f.attr == "path":
                    chain = _attr_chain(f)
                    if chain.endswith("sys.path"):
                        violations.append(f"attr {chain}")
        elif isinstance(node, ast.Subscript):
            chain = _attr_chain(node.value)
            if chain.endswith("sys.path"):
                violations.append(f"subscript {chain}")
    return violations


def _check_module_purity(path: Path, label: str) -> None:
    source = path.read_text()
    for name in _imports_of(path):
        top = name.split(".")[0]
        assert top in (
            _ALLOWED_STDLIB | _ALLOWED_LOCAL_MODULES
            | _ALLOWED_LOCAL_PARENT_PACKAGES
        ), f"{label}: forbidden import: {name}"
    tree = ast.parse(source)
    v = _top_level_io_violations(tree)
    assert v == [], f"{label}: top-level I/O calls: {v}"
    dyn = _all_dynamic_import_violations(tree)
    assert dyn == [], (
        f"{label}: dynamic import / path / loader violations: {dyn}"
    )
    for stmt in tree.body:
        if isinstance(
            stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            continue
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Name) and f.id in (
                    "__import__", "eval", "exec", "compile",
                ):
                    raise AssertionError(
                        f"{label}: forbidden top-level call: {f.id}"
                    )
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (isinstance(target, ast.Name)
                        and not target.id.startswith("_")):
                    raise AssertionError(
                        f"{label}: public constant: {target.id}"
                    )
        elif isinstance(node, ast.AnnAssign):
            if (isinstance(node.target, ast.Name)
                    and not node.target.id.startswith("_")):
                raise AssertionError(
                    f"{label}: public constant: {node.target.id}"
                )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in _ALLOWED_LOCAL_MODULES:
                    bind = alias.asname or alias.name
                    assert bind.startswith("_"), (
                        f"{label}: local module imported without "
                        f"private alias: {alias.name}"
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            top = node.module.split(".")[0]
            if top in _ALLOWED_LOCAL_MODULES or top in (
                _ALLOWED_LOCAL_PARENT_PACKAGES
            ):
                for alias in node.names:
                    bind = alias.asname or alias.name
                    assert bind.startswith("_"), (
                        f"{label}: local module imported without "
                        f"private alias: {node.module}.{alias.name}"
                    )


def test_module_source_ast_purity_all_three_modules() -> None:
    _check_module_purity(RESOLVER_PATH, "resolver")
    _check_module_purity(FREEZER_PATH, "freezer")
    _check_module_purity(VERIFIER_PATH, "verifier")


def test_resolver_source_no_platform_literals_or_branches() -> None:
    source = RESOLVER_PATH.read_text()
    lowered = source.lower()
    for lit in PLATFORM_LITERALS:
        assert lit not in lowered, (
            f"resolver: forbidden platform literal: {lit!r}"
        )
    # No ``if platform_id == <literal>`` style branch. We flag only
    # comparisons where one operand is a bare ``platform`` /
    # ``platform_id`` / ``platform_name`` Name and the other is a
    # Constant (string / numeric literal). Identity comparisons
    # against other Names or Subscripts are generic verification, not
    # platform-specific branching.
    tree = ast.parse(source)
    flagged = ("platform", "platform_id", "platform_name")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left, *node.comparators]
        name_ids = {op.id for op in operands if isinstance(op, ast.Name)}
        if (any(n in flagged for n in name_ids)
                and any(isinstance(op, ast.Constant) for op in operands)):
            raise AssertionError(
                f"resolver: forbidden platform-specific branch: "
                f"{ast.dump(node)}"
            )


def test_no_production_module_imports_a_package_wrapper() -> None:
    forbidden_prefixes = (
        "flutter_package_v1", "vue_package_v1", "nextjs_package_v1",
        "ios_swift_package_v1", "ios_objc_package_v1",
        "android_kotlin_package_v1", "android_java_package_v1",
    )
    for path, label in (
        (RESOLVER_PATH, "resolver"),
        (FREEZER_PATH, "freezer"),
        (VERIFIER_PATH, "verifier"),
    ):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for forb in forbidden_prefixes:
                        assert not alias.name.startswith(forb), (
                            f"{label}: imports {alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom):
                if node.module is None:
                    continue
                for forb in forbidden_prefixes:
                    assert not node.module.startswith(forb), (
                        f"{label}: from-imports {node.module}"
                    )


# ---------------------------------------------------------------------------
# 13. Modules import cleanly in a fresh subprocess with icp/scripts on
#     PYTHONPATH (regression across P3a / P3a2 / P3b1a / P3b1b1).
# ---------------------------------------------------------------------------def test_modules_import_cleanly_in_fresh_subprocess() -> None:
    code = (
        "import platform_package_resolver_v1 as r;"
        "import freeze_platform_package_selection_v1 as f;"
        "import verify_platform_package_selection_v1 as v;"
        "import entry_readiness_v1 as e;"
        "import requirement_progress_v1 as p;"
        "from platforms import platform_package_contract_v1 as c;"
        "print('IMPORT_OK');"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
             "PYTHONPATH": str(ICP_SCRIPTS)},
    )
    assert result.returncode == 0, (
        f"fresh import failed: rc={result.returncode} stderr={result.stderr}"
    )
    assert result.stdout.strip() == "IMPORT_OK"


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
