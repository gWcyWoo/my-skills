#!/usr/bin/env python3
"""Vertical RED -> GREEN selftest for the ICP P2e2a non-executable
Flutter execution authorization candidate
(``platforms/flutter_execution_authorization_v1``).

P2e2a produces a deterministic, **non-executable**, unsigned candidate
``icp.flutter-execution-authorization-candidate`` envelope from an
existing verified ``icp.flutter-execution-binding.v1`` binding. The
candidate is **not** self-authorizing authority: the trusted supervisor
must retain the canonical selection-manifest path, selection-manifest
SHA-256, verified binding digest, and prepared authorization digest out
of band. ``verify_authorization`` requires all four expected values; an
attacker who rewrites workspace files and recomputes in-document
digests cannot authorize a different valid binding.

This slice performs **no execution**: no command, no receipt, no
project/state/run-root mutation, no network, no platform adapter
activation. It does not consume the execution nonce; P2e2b must claim
the nonce atomically at spawn time.

The tests build a real frozen selection manifest through the real
freezer, drive the real binding builder (with the Flutter preflight's
``flutter --version --machine`` subprocess stubbed in-process), then
prepare/verify authorizations through the real authorization module.
No production file (capsule, descriptor, manifest, registry,
``iff/**``, existing project files) is mutated.

Run directly:

    PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p2e2a_flutter_authorization.py
"""

from __future__ import annotations

import ast
import contextlib
import copy
import hashlib
import importlib.util
import inspect
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
ICP_ROOT = Path(__file__).resolve().parents[1]
ICP_SCRIPTS = Path(__file__).resolve().parent
PLATFORMS_DIR = ICP_SCRIPTS / "platforms"
AUTHZ_PATH = PLATFORMS_DIR / "flutter_execution_authorization_v1.py"
BINDING_PATH = PLATFORMS_DIR / "flutter_execution_binding_v1.py"
OPERATIONS_PATH = PLATFORMS_DIR / "flutter_operations_v1.py"
PREFLIGHT_PATH = PLATFORMS_DIR / "flutter_project_preflight_v1.py"
DESCRIPTOR_PATH = PLATFORMS_DIR / "flutter_standard_v1.py"
FREEZE_PATH = ICP_SCRIPTS / "freeze_selection_manifest.py"
COMMON_PATH = ICP_SCRIPTS / "icp_common.py"
VERIFY_SEL_PATH = ICP_SCRIPTS / "verify_selection_manifest_v1.py"
MANIFEST_PATH = ICP_ROOT / "references" / "baselines" / "iff-v1-vendor.json"
REGISTRY_PATH = ICP_ROOT / "references" / "registries.json"
SKILL_MD_PATH = ICP_ROOT / "SKILL.md"

KIND_AUTHZ = "icp.flutter-execution-authorization-candidate"
KIND_AUTHZ_VERIFY = "icp.flutter-execution-authorization-verify.v1"
SCHEMA_VERSION = 1

# Canonical (compact-separator) JSON used by the authorization module.
# Distinct from the binding's indent=2 canonical form.


def _canonical_compact(obj: Any) -> bytes:
    return json.dumps(
        obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _is_sha256_hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value.islower()
        and all(c in "0123456789abcdef" for c in value)
    )


# ---------------------------------------------------------------------------
# Module loaders.
# ---------------------------------------------------------------------------


def _load(name: str, path: Path = AUTHZ_PATH):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_freeze(name: str = "p2e2a_freeze_helper"):
    return _load(name, FREEZE_PATH)


def _load_common(name: str = "p2e2a_common_helper"):
    return _load(name, COMMON_PATH)


# ---------------------------------------------------------------------------
# Fake Flutter plumbing (stub the preflight module's shutil/subprocess only).
# ---------------------------------------------------------------------------


class _FakeCompletedProcess:
    def __init__(self, *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _FakeShutil:
    def __init__(self, which_fn) -> None:
        self.which = which_fn


class _FakeSubprocess:
    PIPE = subprocess.PIPE
    TimeoutExpired = subprocess.TimeoutExpired

    def __init__(self, run_fn) -> None:
        self.run = run_fn


def _default_version_payload() -> dict[str, Any]:
    return {
        "frameworkVersion": "3.24.5",
        "channel": "stable",
        "repositoryUrl": "https://github.com/flutter/flutter.git",
        "frameworkRevision": "abc123",
        "frameworkCommitHash": "abc123",
        "engineRevision": "def456",
        "engineCommitHash": "def456",
        "dartSdkVersion": "3.5.4",
        "devToolsVersion": "2.27.0",
        "flutterRoot": "/opt/flutter",
    }


def _install_fake_flutter(preflight_module) -> Path:
    fd, path_str = tempfile.mkstemp(prefix="fake_flutter_")
    os.close(fd)
    resolved = Path(os.path.realpath(path_str))
    resolved.write_text("#!/bin/sh\necho fake\n", encoding="utf-8")
    os.chmod(resolved, 0o755)
    payload = _default_version_payload()
    stdout_text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    def _fake_which(name: str):
        if name == "flutter":
            return str(resolved)
        return None

    def _fake_run(args, **kwargs):
        return _FakeCompletedProcess(returncode=0, stdout=stdout_text, stderr="")

    preflight_module.shutil = _FakeShutil(_fake_which)
    preflight_module.subprocess = _FakeSubprocess(_fake_run)
    return resolved


@contextlib.contextmanager
def _with_fake_preflight(binding_module):
    """Force the binding module to load its preflight module, then patch
    the preflight module's shutil/subprocess so the binding's preflight
    call succeeds without a host Flutter installation."""
    preflight_module = binding_module._load_preflight_module()
    saved_shutil = preflight_module.shutil
    saved_subprocess = preflight_module.subprocess
    try:
        _install_fake_flutter(preflight_module)
        yield preflight_module
    finally:
        preflight_module.shutil = saved_shutil
        preflight_module.subprocess = saved_subprocess


# ---------------------------------------------------------------------------
# Canonical fixture builders (real freezer + real binding builder).
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _canonical_tempdir(prefix: str = "p2e2a_"):
    with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
        yield Path(os.path.realpath(str(tmp)))


def _write_json(path: Path, payload: Any) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.write_bytes(data)
    return data


def _build_minimal_flutter_project(proj: Path, *, name: str = "my_app") -> None:
    (proj / "lib").mkdir(parents=True, exist_ok=True)
    (proj / "lib" / "main.dart").write_text("// main\n", encoding="utf-8")
    (proj / "pubspec.yaml").write_text(f"name: {name}\n", encoding="utf-8")
    dart_tool = proj / ".dart_tool"
    dart_tool.mkdir(parents=True, exist_ok=True)
    pkg_cfg = {
        "configVersion": 2,
        "generated": "2024-01-01T00:00:00.000Z",
        "generator": "pub",
        "generatorVersion": "3.5.4",
        "flutterRoot": "/opt/flutter",
        "packages": [
            {"name": name, "rootUri": "../", "packageUri": "lib/", "languageVersion": "3.0"}
        ],
    }
    (dart_tool / "package_config.json").write_text(
        json.dumps(pkg_cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _good_cands() -> list[dict[str, Any]]:
    return [
        {"row_index": 1, "title": "Alpha", "status": "",
         "design_url": "https://figma.com/file/a"},
        {"row_index": 2, "title": "Beta", "status": "",
         "design_url": "https://lanhuapp.com/url/b"},
    ]


def _resolved(project_root: Path) -> dict[str, Any]:
    return {
        "task_source": "csv",
        "task_ref": "tasks.csv",
        "design_source": "lanhu-figma",
        "platform": "flutter",
        "profile": "flutter-standard",
        "project_root": str(project_root),
    }


@contextlib.contextmanager
def _frozen_canonical_flutter_project(batch_id: str = "p2e2a-batch-1"):
    freeze = _load_freeze()
    common = _load_common()
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        proj.mkdir()
        _build_minimal_flutter_project(proj)
        ack = freeze.freeze_selection_manifest(
            resolved_config=_resolved(proj),
            candidates=_good_cands(),
            batch_id=batch_id,
            registries=common.load_registries(),
        )
        run_root = Path(ack["run_root"])
        yield proj, run_root, Path(ack["manifest_path"])


def _fixture_request(proj: Path, run_root: Path) -> dict[str, Any]:
    # P2.5b: fixture_codegen now requires a projections map matching
    # the slots state set; each value is an existing .json under
    # run_root.
    _write_json(run_root / "state_a.json", {"a": 1})
    _write_json(run_root / "proj_a.json", {"p": 1})
    return {
        "project_root": str(proj),
        "run_root": str(run_root),
        "package_name": "my_app",
        "feature_id": "fancy_widget",
        "slots": {"state_a": "state_a.json"},
        "projections": {"state_a": "proj_a.json"},
        "out": "lib/fixture.dart",
    }


def _fan_in_done_gate_request(proj: Path, spec_root: Path) -> dict[str, Any]:
    return {
        "project_root": str(proj),
        "spec_root": str(spec_root),
        "action": "done_gate",
    }


def _visible_request(proj: Path, run_root: Path) -> dict[str, Any]:
    for name, payload in (
        ("render_plan.json", {"a": 1}),
        ("classification.json", {"a": 1}),
        ("component_manifest.json", {"a": 1}),
        ("scene.json", {"a": 1}),
    ):
        _write_json(run_root / name, payload)
    return {
        "project_root": str(proj),
        "run_root": str(run_root),
        "package_name": "my_app",
        "feature_id": "fancy_widget",
        "render_plan": "render_plan.json",
        "classification": "classification.json",
        "component_manifest": "component_manifest.json",
        "scene": "scene.json",
        "canvas_out": "lib/canvas.dart",
        "colors_out": "lib/colors.dart",
        "status_bar_out": "lib/status_bar.dart",
        "implementation_map_out": "impl_map.json",
        "colors_import_path": "lib/colors.dart",
        "canvas_class_name": "CanvasWidget",
        "status_bar_class_name": "StatusBarPolicy",
    }


@contextlib.contextmanager
def _build_verified_binding(authz_module, operation_id: str, request_factory):
    """Build a real verified binding through the real binding builder,
    using the authorization module's own binding-module instance.

    Yields ``(binding_module, binding, manifest_path, project_root,
    spec_root, expected_tuple)`` where ``expected_tuple`` is the
    supervisor-held out-of-band trust anchor
    ``(manifest_path_str, manifest_sha, binding_digest, nonce)``.

    The frozen project / manifest AND the in-process fake Flutter
    preflight remain alive for the duration of the ``with`` block so
    that ``prepare_authorization`` and ``verify_authorization`` (which
    both re-attest the embedded binding through ``verify_binding``)
    re-read the manifest bytes and reproduce the exact same preflight
    report. The fake preflight is installed on the exact same binding
    module instance used by ``prepare_authorization`` /
    ``verify_authorization`` (the authorization module's
    ``_load_binding_module()``), so the in-process fake is in effect
    for every re-attestation."""
    binding_module = authz_module._load_binding_module()
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(binding_module):
            request = request_factory(proj, spec)
            binding = binding_module.prepare_binding(mp, operation_id, request)
            verify_report = binding_module.verify_binding(binding)
            manifest_sha = hashlib.sha256(mp.read_bytes()).hexdigest()
            binding_digest = verify_report["binding_digest"]
            nonce = "0123456789abcdef0123456789abcdef"
            expected_tuple = (str(mp), manifest_sha, binding_digest, nonce)
            yield binding_module, binding, mp, proj, spec, expected_tuple


# ---------------------------------------------------------------------------
# 1. Module surface.
# ---------------------------------------------------------------------------


def test_module_loads() -> None:
    module = _load("p2e2a_loads")
    assert module.KIND_AUTHZ == KIND_AUTHZ
    assert module.KIND_AUTHZ_VERIFY == KIND_AUTHZ_VERIFY
    assert module.SCHEMA_VERSION == SCHEMA_VERSION
    assert module.PLATFORM_ID == "flutter"
    assert module.PROFILE_ID == "flutter-standard"
    assert module.ACTIVATION_STATE == "inactive"
    assert module.EXECUTABLE is False
    assert hasattr(module, "CODE")
    assert isinstance(module.CODE, str) and module.CODE


def test_module_exposes_typed_exception() -> None:
    module = _load("p2e2a_exc")
    assert hasattr(module, "FlutterExecutionAuthorizationError")
    assert issubclass(module.FlutterExecutionAuthorizationError, Exception)


def test_module_has_no_cli_main() -> None:
    module = _load("p2e2a_nocli")
    assert not hasattr(module, "main")
    source = AUTHZ_PATH.read_text()
    assert '__name__ == "__main__"' not in source
    assert "import argparse" not in source
    assert "sys.argv" not in source


def test_public_api_exposes_only_two_funcs_and_exception() -> None:
    module = _load("p2e2a_pubapi")
    assert callable(module.prepare_authorization)
    assert callable(module.verify_authorization)
    allowed_funcs = {"prepare_authorization", "verify_authorization"}
    public_funcs = [
        n
        for n in dir(module)
        if not n.startswith("_")
        and inspect.isfunction(getattr(module, n))
        and getattr(module, n).__module__ == module.__name__
    ]
    extra = sorted(set(public_funcs) - allowed_funcs)
    assert extra == [], f"unexpected public functions: {extra}"
    allowed_classes = {"FlutterExecutionAuthorizationError"}
    public_classes = [
        n
        for n in dir(module)
        if not n.startswith("_")
        and inspect.isclass(getattr(module, n))
        and getattr(module, n).__module__ == module.__name__
    ]
    extra_c = sorted(set(public_classes) - allowed_classes)
    assert extra_c == [], f"unexpected public classes: {extra_c}"


def test_module_does_not_import_subprocess_or_network_or_write() -> None:
    _assert_no_forbidden_surface(AUTHZ_PATH.read_text(), role=AUTHZ_PATH)


# ---------------------------------------------------------------------------
# 2. Happy path through real freezer / verifier / binding.
# ---------------------------------------------------------------------------


def _assert_happy_path_fields(authorization, binding, manifest_path_str, manifest_sha, binding_digest, nonce) -> None:
    expected_keys = {
        "kind", "schema_version", "platform_id", "profile_id",
        "activation_state", "executable", "operation_id", "port_id",
        "capability_state", "selection_manifest_path",
        "selection_manifest_sha256", "binding_digest", "execution_nonce",
        "verified_binding", "step_authorizations", "authorization_digest",
    }
    assert set(authorization.keys()) == expected_keys, (
        set(authorization.keys()) ^ expected_keys
    )
    assert authorization["kind"] == KIND_AUTHZ
    assert authorization["schema_version"] == SCHEMA_VERSION
    assert authorization["platform_id"] == "flutter"
    assert authorization["profile_id"] == "flutter-standard"
    assert authorization["activation_state"] == "inactive"
    assert authorization["executable"] is False
    assert authorization["selection_manifest_path"] == manifest_path_str
    assert authorization["selection_manifest_sha256"] == manifest_sha
    assert authorization["binding_digest"] == binding_digest
    assert authorization["execution_nonce"] == nonce
    assert authorization["verified_binding"] == binding
    assert authorization["verified_binding"] is not binding
    steps = authorization["step_authorizations"]
    assert isinstance(steps, list)
    assert len(steps) == len(binding["plan"]["steps"])
    step_keys = {
        "step_id", "primitive", "primitive_path", "primitive_sha256",
        "argv_digest", "cwd", "timeout_seconds", "executable_path",
        "executable_sha256", "step_authorization_digest",
    }
    for i, sa in enumerate(steps):
        assert set(sa.keys()) == step_keys, (i, set(sa.keys()) ^ step_keys)
        bs = binding["plan"]["steps"][i]
        assert sa["step_id"] == bs["step_id"]
        assert sa["primitive"] == bs["primitive"]
        assert sa["primitive_sha256"] == bs["primitive_sha256"]
        assert sa["cwd"] == bs["cwd"]
        assert sa["timeout_seconds"] == bs["timeout_seconds"]
        assert sa["executable_path"] == os.path.realpath(sys.executable)
        assert sa["executable_path"] == os.path.realpath(bs["argv"][0])
        assert sa["executable_sha256"] == hashlib.sha256(
            Path(sys.executable).read_bytes()
        ).hexdigest()
        assert sa["primitive_path"] == os.path.realpath(bs["argv"][1])
        actual_prim_sha = hashlib.sha256(
            Path(bs["argv"][1]).read_bytes()
        ).hexdigest()
        assert sa["primitive_sha256"] == actual_prim_sha
        expected_argv_digest = hashlib.sha256(
            _canonical_compact(bs["argv"])
        ).hexdigest()
        assert sa["argv_digest"] == expected_argv_digest
        payload = {k: v for k, v in sa.items() if k != "step_authorization_digest"}
        expected_step_digest = hashlib.sha256(_canonical_compact(payload)).hexdigest()
        assert sa["step_authorization_digest"] == expected_step_digest
        assert isinstance(sa["timeout_seconds"], int)
        assert not isinstance(sa["timeout_seconds"], bool)
    payload = {k: v for k, v in authorization.items() if k != "authorization_digest"}
    expected_authz_digest = hashlib.sha256(_canonical_compact(payload)).hexdigest()
    assert authorization["authorization_digest"] == expected_authz_digest
    assert _is_sha256_hex(authorization["authorization_digest"])


def test_prepare_authorization_fixture_codegen_succeeds() -> None:
    authz_module = _load("p2e2a_prep_fixture")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        authorization = authz_module.prepare_authorization(
            binding,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            execution_nonce=nonce,
        )
    assert authorization["operation_id"] == "flutter.fixture_codegen.v1"
    assert authorization["port_id"] == "fixture_codegen"
    assert authorization["capability_state"] == "required"
    _assert_happy_path_fields(
        authorization, binding, manifest_path_str, manifest_sha, binding_digest, nonce
    )


def test_prepare_authorization_fan_in_done_gate_succeeds() -> None:
    authz_module = _load("p2e2a_prep_fanin")
    with _build_verified_binding(
        authz_module, "flutter.fan_in.v1", _fan_in_done_gate_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        authorization = authz_module.prepare_authorization(
            binding,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            execution_nonce=nonce,
        )
    assert authorization["operation_id"] == "flutter.fan_in.v1"
    assert authorization["port_id"] == "fan_in"
    assert authorization["capability_state"] == "required"
    assert authorization["executable"] is False
    assert len(authorization["step_authorizations"]) == len(binding["plan"]["steps"])


def test_prepare_authorization_is_deterministic() -> None:
    authz_module = _load("p2e2a_det")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        a1 = authz_module.prepare_authorization(
            binding,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            execution_nonce=nonce,
        )
        a2 = authz_module.prepare_authorization(
            binding,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            execution_nonce=nonce,
        )
    assert a1 == a2


def test_verify_authorization_accepts_fresh_prepared_fixture() -> None:
    authz_module = _load("p2e2a_verify_fixture")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        authorization = authz_module.prepare_authorization(
            binding,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            execution_nonce=nonce,
        )
        expected_authz_digest = authorization["authorization_digest"]
        report = authz_module.verify_authorization(
            authorization,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            expected_authorization_digest=expected_authz_digest,
        )
    assert report["ok"] is True
    assert report["kind"] == KIND_AUTHZ_VERIFY
    assert report["schema_version"] == SCHEMA_VERSION
    expected_keys = {
        "ok", "kind", "schema_version", "platform_id", "operation_id",
        "port_id", "binding_digest", "selection_manifest_sha256",
        "authorization_digest", "execution_nonce",
    }
    assert set(report.keys()) == expected_keys, set(report.keys()) ^ expected_keys
    assert report["operation_id"] == "flutter.fixture_codegen.v1"
    assert report["port_id"] == "fixture_codegen"
    assert report["binding_digest"] == binding_digest
    assert report["selection_manifest_sha256"] == manifest_sha
    assert report["authorization_digest"] == expected_authz_digest
    assert report["execution_nonce"] == nonce


def test_verify_authorization_accepts_fresh_prepared_fan_in() -> None:
    authz_module = _load("p2e2a_verify_fanin")
    with _build_verified_binding(
        authz_module, "flutter.fan_in.v1", _fan_in_done_gate_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        authorization = authz_module.prepare_authorization(
            binding,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            execution_nonce=nonce,
        )
        report = authz_module.verify_authorization(
            authorization,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            expected_authorization_digest=authorization["authorization_digest"],
        )
    assert report["ok"] is True
    assert report["operation_id"] == "flutter.fan_in.v1"


def test_verify_authorization_is_deterministic() -> None:
    authz_module = _load("p2e2a_verify_det")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        authorization = authz_module.prepare_authorization(
            binding,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            execution_nonce=nonce,
        )
        r1 = authz_module.verify_authorization(
            authorization,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            expected_authorization_digest=authorization["authorization_digest"],
        )
        r2 = authz_module.verify_authorization(
            authorization,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            expected_authorization_digest=authorization["authorization_digest"],
        )
    assert r1 == r2


# ---------------------------------------------------------------------------
# 3. Each out-of-band expected value mismatch independently.
# ---------------------------------------------------------------------------


def test_verify_rejects_manifest_path_mismatch() -> None:
    authz_module = _load("p2e2a_vm_mp")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        authorization = authz_module.prepare_authorization(
            binding,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            execution_nonce=nonce,
        )
        try:
            authz_module.verify_authorization(
                authorization,
                expected_manifest_path=manifest_path_str + "/tampered",
                expected_manifest_sha256=manifest_sha,
                expected_binding_digest=binding_digest,
                expected_authorization_digest=authorization["authorization_digest"],
            )
        except authz_module.FlutterExecutionAuthorizationError:
            pass
        else:
            raise AssertionError("manifest_path mismatch accepted")


def test_verify_rejects_manifest_sha_mismatch() -> None:
    authz_module = _load("p2e2a_vm_ms")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        authorization = authz_module.prepare_authorization(
            binding,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            execution_nonce=nonce,
        )
        try:
            authz_module.verify_authorization(
                authorization,
                expected_manifest_path=manifest_path_str,
                expected_manifest_sha256="a" * 64,
                expected_binding_digest=binding_digest,
                expected_authorization_digest=authorization["authorization_digest"],
            )
        except authz_module.FlutterExecutionAuthorizationError:
            pass
        else:
            raise AssertionError("manifest_sha mismatch accepted")


def test_verify_rejects_binding_digest_mismatch() -> None:
    authz_module = _load("p2e2a_vm_bd")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        authorization = authz_module.prepare_authorization(
            binding,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            execution_nonce=nonce,
        )
        try:
            authz_module.verify_authorization(
                authorization,
                expected_manifest_path=manifest_path_str,
                expected_manifest_sha256=manifest_sha,
                expected_binding_digest="b" * 64,
                expected_authorization_digest=authorization["authorization_digest"],
            )
        except authz_module.FlutterExecutionAuthorizationError:
            pass
        else:
            raise AssertionError("binding_digest mismatch accepted")


def test_verify_rejects_authorization_digest_mismatch() -> None:
    authz_module = _load("p2e2a_vm_ad")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        authorization = authz_module.prepare_authorization(
            binding,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            execution_nonce=nonce,
        )
        try:
            authz_module.verify_authorization(
                authorization,
                expected_manifest_path=manifest_path_str,
                expected_manifest_sha256=manifest_sha,
                expected_binding_digest=binding_digest,
                expected_authorization_digest="c" * 64,
            )
        except authz_module.FlutterExecutionAuthorizationError:
            pass
        else:
            raise AssertionError("authorization_digest mismatch accepted")


# ---------------------------------------------------------------------------
# 4. Authorization digest tamper and recomputation attack.
# ---------------------------------------------------------------------------


def test_verify_rejects_authorization_digest_tamper() -> None:
    authz_module = _load("p2e2a_ad_tamper")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        authorization = authz_module.prepare_authorization(
            binding,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            execution_nonce=nonce,
        )
        tampered = copy.deepcopy(authorization)
        tampered["authorization_digest"] = "d" * 64
        try:
            authz_module.verify_authorization(
                tampered,
                expected_manifest_path=manifest_path_str,
                expected_manifest_sha256=manifest_sha,
                expected_binding_digest=binding_digest,
                expected_authorization_digest=authorization["authorization_digest"],
            )
        except authz_module.FlutterExecutionAuthorizationError:
            pass
        else:
            raise AssertionError("authorization_digest tamper accepted")


def test_verify_rejects_coordinated_recompute_attack() -> None:
    """A fully coordinated attacker rewrite that recomputes every in-
    document digest (step + top-level authorization_digest) is still
    rejected by the unchanged out-of-band expected authorization
    digest."""
    authz_module = _load("p2e2a_ad_coordinated")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        authorization = authz_module.prepare_authorization(
            binding,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            execution_nonce=nonce,
        )
        original_digest = authorization["authorization_digest"]
        tampered = copy.deepcopy(authorization)
        tampered["execution_nonce"] = "fedcba9876543210fedcba9876543210"
        for sa in tampered["step_authorizations"]:
            payload = {k: v for k, v in sa.items() if k != "step_authorization_digest"}
            sa["step_authorization_digest"] = hashlib.sha256(
                _canonical_compact(payload)
            ).hexdigest()
        top_payload = {
            k: v for k, v in tampered.items() if k != "authorization_digest"
        }
        tampered["authorization_digest"] = hashlib.sha256(
            _canonical_compact(top_payload)
        ).hexdigest()
        assert tampered["authorization_digest"] != original_digest
        try:
            authz_module.verify_authorization(
                tampered,
                expected_manifest_path=manifest_path_str,
                expected_manifest_sha256=manifest_sha,
                expected_binding_digest=binding_digest,
                expected_authorization_digest=original_digest,
            )
        except authz_module.FlutterExecutionAuthorizationError:
            pass
        else:
            raise AssertionError("coordinated recompute attack accepted")


# ---------------------------------------------------------------------------
# 5. Manifest path/hash and binding digest tampering at prepare time.
# ---------------------------------------------------------------------------


def test_prepare_rejects_manifest_path_mismatch() -> None:
    authz_module = _load("p2e2a_pm_mp")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        try:
            authz_module.prepare_authorization(
                binding,
                expected_manifest_path=manifest_path_str + "/x",
                expected_manifest_sha256=manifest_sha,
                expected_binding_digest=binding_digest,
                execution_nonce=nonce,
            )
        except authz_module.FlutterExecutionAuthorizationError:
            pass
        else:
            raise AssertionError("prepare accepted manifest_path mismatch")


def test_prepare_rejects_manifest_sha_mismatch() -> None:
    authz_module = _load("p2e2a_pm_ms")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        try:
            authz_module.prepare_authorization(
                binding,
                expected_manifest_path=manifest_path_str,
                expected_manifest_sha256="e" * 64,
                expected_binding_digest=binding_digest,
                execution_nonce=nonce,
            )
        except authz_module.FlutterExecutionAuthorizationError:
            pass
        else:
            raise AssertionError("prepare accepted manifest_sha mismatch")


def test_prepare_rejects_binding_digest_mismatch() -> None:
    authz_module = _load("p2e2a_pm_bd")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        try:
            authz_module.prepare_authorization(
                binding,
                expected_manifest_path=manifest_path_str,
                expected_manifest_sha256=manifest_sha,
                expected_binding_digest="f" * 64,
                execution_nonce=nonce,
            )
        except authz_module.FlutterExecutionAuthorizationError:
            pass
        else:
            raise AssertionError("prepare accepted binding_digest mismatch")


def test_prepare_rejects_manifest_sha_vs_binding_mismatch() -> None:
    """expected_manifest_sha256 must equal the verified binding's
    selection_manifest_sha256; the trusted anchor and the embedded
    binding must agree."""
    authz_module = _load("p2e2a_pm_ms_binding")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        wrong_sha = "0" * 64
        assert wrong_sha != manifest_sha
        try:
            authz_module.prepare_authorization(
                binding,
                expected_manifest_path=manifest_path_str,
                expected_manifest_sha256=wrong_sha,
                expected_binding_digest=binding_digest,
                execution_nonce=nonce,
            )
        except authz_module.FlutterExecutionAuthorizationError:
            pass
        else:
            raise AssertionError("prepare accepted manifest sha != binding sha")


# ---------------------------------------------------------------------------
# 6. Nonce grammar (caller-supplied, exactly 32 lowercase hex chars).
# ---------------------------------------------------------------------------


def _good_kwargs(binding, expected, **overrides):
    manifest_path_str, manifest_sha, binding_digest, nonce = expected
    kwargs = dict(
        binding=binding,
        expected_manifest_path=manifest_path_str,
        expected_manifest_sha256=manifest_sha,
        expected_binding_digest=binding_digest,
        execution_nonce=nonce,
    )
    kwargs.update(overrides)
    return kwargs


def test_prepare_rejects_nonce_newline() -> None:
    authz_module = _load("p2e2a_nonce_nl")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        try:
            authz_module.prepare_authorization(
                **_good_kwargs(binding, expected, execution_nonce="0123456789abcdef0123456789abcde\n")
            )
        except authz_module.FlutterExecutionAuthorizationError:
            pass
        else:
            raise AssertionError("newline nonce accepted")


def test_prepare_rejects_nonce_crlf() -> None:
    authz_module = _load("p2e2a_nonce_crlf")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        try:
            authz_module.prepare_authorization(
                **_good_kwargs(binding, expected, execution_nonce="0123456789abcdef0123456789abcde\r\n")
            )
        except authz_module.FlutterExecutionAuthorizationError:
            pass
        else:
            raise AssertionError("crlf nonce accepted")


def test_prepare_rejects_nonce_trailing_space() -> None:
    authz_module = _load("p2e2a_nonce_sp")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        try:
            authz_module.prepare_authorization(
                **_good_kwargs(binding, expected, execution_nonce="0123456789abcdef0123456789abcde ")
            )
        except authz_module.FlutterExecutionAuthorizationError:
            pass
        else:
            raise AssertionError("trailing-space nonce accepted")


def test_prepare_rejects_nonce_uppercase() -> None:
    authz_module = _load("p2e2a_nonce_uc")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        try:
            authz_module.prepare_authorization(
                **_good_kwargs(binding, expected, execution_nonce="0123456789ABCDEF0123456789abcdef")
            )
        except authz_module.FlutterExecutionAuthorizationError:
            pass
        else:
            raise AssertionError("uppercase nonce accepted")


def test_prepare_rejects_nonce_31_chars() -> None:
    authz_module = _load("p2e2a_nonce_31")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        try:
            authz_module.prepare_authorization(
                **_good_kwargs(binding, expected, execution_nonce="0123456789abcdef0123456789abcde")
            )
        except authz_module.FlutterExecutionAuthorizationError:
            pass
        else:
            raise AssertionError("31-char nonce accepted")


def test_prepare_rejects_nonce_33_chars() -> None:
    authz_module = _load("p2e2a_nonce_33")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        try:
            authz_module.prepare_authorization(
                **_good_kwargs(binding, expected, execution_nonce="0123456789abcdef0123456789abcdef0")
            )
        except authz_module.FlutterExecutionAuthorizationError:
            pass
        else:
            raise AssertionError("33-char nonce accepted")


def test_prepare_rejects_nonce_non_string() -> None:
    authz_module = _load("p2e2a_nonce_nstr")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        try:
            authz_module.prepare_authorization(
                **_good_kwargs(binding, expected, execution_nonce=1234567890)
            )
        except authz_module.FlutterExecutionAuthorizationError:
            pass
        else:
            raise AssertionError("non-string nonce accepted")


def test_prepare_rejects_nonce_bytes() -> None:
    authz_module = _load("p2e2a_nonce_bytes")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        try:
            authz_module.prepare_authorization(
                **_good_kwargs(binding, expected, execution_nonce=b"0123456789abcdef0123456789abcdef")
            )
        except authz_module.FlutterExecutionAuthorizationError:
            pass
        else:
            raise AssertionError("bytes nonce accepted")


def test_verify_rejects_nonce_tamper_in_authorization() -> None:
    authz_module = _load("p2e2a_nonce_tamper")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        authorization = authz_module.prepare_authorization(
            binding,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            execution_nonce=nonce,
        )
        tampered = copy.deepcopy(authorization)
        tampered["execution_nonce"] = "fedcba9876543210fedcba9876543210"
        try:
            authz_module.verify_authorization(
                tampered,
                expected_manifest_path=manifest_path_str,
                expected_manifest_sha256=manifest_sha,
                expected_binding_digest=binding_digest,
                expected_authorization_digest=authorization["authorization_digest"],
            )
        except authz_module.FlutterExecutionAuthorizationError:
            pass
        else:
            raise AssertionError("embedded nonce tamper accepted")


# ---------------------------------------------------------------------------
# 7. Top-level and per-step extra/missing keys.
# ---------------------------------------------------------------------------


def test_verify_rejects_top_level_extra_key() -> None:
    authz_module = _load("p2e2a_top_extra")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        authorization = authz_module.prepare_authorization(
            binding,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            execution_nonce=nonce,
        )
        tampered = copy.deepcopy(authorization)
        tampered["extra_top"] = "boom"
        try:
            authz_module.verify_authorization(
                tampered,
                expected_manifest_path=manifest_path_str,
                expected_manifest_sha256=manifest_sha,
                expected_binding_digest=binding_digest,
                expected_authorization_digest=authorization["authorization_digest"],
            )
        except authz_module.FlutterExecutionAuthorizationError:
            pass
        else:
            raise AssertionError("top-level extra key accepted")


def test_verify_rejects_top_level_missing_key() -> None:
    authz_module = _load("p2e2a_top_missing")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        authorization = authz_module.prepare_authorization(
            binding,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            execution_nonce=nonce,
        )
        for k in list(authorization.keys()):
            tampered = copy.deepcopy(authorization)
            del tampered[k]
            try:
                authz_module.verify_authorization(
                    tampered,
                    expected_manifest_path=manifest_path_str,
                    expected_manifest_sha256=manifest_sha,
                    expected_binding_digest=binding_digest,
                    expected_authorization_digest=authorization["authorization_digest"],
                )
            except authz_module.FlutterExecutionAuthorizationError:
                pass
            else:
                raise AssertionError(f"missing top-level key {k!r} accepted")


def test_verify_rejects_step_extra_key() -> None:
    authz_module = _load("p2e2a_step_extra")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        authorization = authz_module.prepare_authorization(
            binding,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            execution_nonce=nonce,
        )
        tampered = copy.deepcopy(authorization)
        tampered["step_authorizations"][0]["extra_step"] = "boom"
        try:
            authz_module.verify_authorization(
                tampered,
                expected_manifest_path=manifest_path_str,
                expected_manifest_sha256=manifest_sha,
                expected_binding_digest=binding_digest,
                expected_authorization_digest=authorization["authorization_digest"],
            )
        except authz_module.FlutterExecutionAuthorizationError:
            pass
        else:
            raise AssertionError("step extra key accepted")


def test_verify_rejects_step_missing_key() -> None:
    authz_module = _load("p2e2a_step_missing")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        authorization = authz_module.prepare_authorization(
            binding,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            execution_nonce=nonce,
        )
        for k in list(authorization["step_authorizations"][0].keys()):
            tampered = copy.deepcopy(authorization)
            del tampered["step_authorizations"][0][k]
            try:
                authz_module.verify_authorization(
                    tampered,
                    expected_manifest_path=manifest_path_str,
                    expected_manifest_sha256=manifest_sha,
                    expected_binding_digest=binding_digest,
                    expected_authorization_digest=authorization["authorization_digest"],
                )
            except authz_module.FlutterExecutionAuthorizationError:
                pass
            else:
                raise AssertionError(f"missing step key {k!r} accepted")


# ---------------------------------------------------------------------------
# 8. Embedded binding request/plan/step tampering.
# ---------------------------------------------------------------------------


def test_verify_rejects_embedded_binding_request_tamper() -> None:
    authz_module = _load("p2e2a_emb_req")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        authorization = authz_module.prepare_authorization(
            binding,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            execution_nonce=nonce,
        )
        tampered = copy.deepcopy(authorization)
        tampered["verified_binding"]["request"]["feature_id"] = "tampered_id"
        try:
            authz_module.verify_authorization(
                tampered,
                expected_manifest_path=manifest_path_str,
                expected_manifest_sha256=manifest_sha,
                expected_binding_digest=binding_digest,
                expected_authorization_digest=authorization["authorization_digest"],
            )
        except authz_module.FlutterExecutionAuthorizationError:
            pass
        else:
            raise AssertionError("embedded request tamper accepted")


def test_verify_rejects_embedded_binding_plan_cwd_tamper() -> None:
    authz_module = _load("p2e2a_emb_cwd")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        authorization = authz_module.prepare_authorization(
            binding,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            execution_nonce=nonce,
        )
        tampered = copy.deepcopy(authorization)
        tampered["verified_binding"]["plan"]["steps"][0]["cwd"] = "/tmp/tampered"
        try:
            authz_module.verify_authorization(
                tampered,
                expected_manifest_path=manifest_path_str,
                expected_manifest_sha256=manifest_sha,
                expected_binding_digest=binding_digest,
                expected_authorization_digest=authorization["authorization_digest"],
            )
        except authz_module.FlutterExecutionAuthorizationError:
            pass
        else:
            raise AssertionError("embedded plan cwd tamper accepted")


def test_verify_rejects_embedded_binding_plan_argv_tamper() -> None:
    authz_module = _load("p2e2a_emb_argv")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        authorization = authz_module.prepare_authorization(
            binding,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            execution_nonce=nonce,
        )
        tampered = copy.deepcopy(authorization)
        tampered["verified_binding"]["plan"]["steps"][0]["argv"].append("--INJECTED")
        try:
            authz_module.verify_authorization(
                tampered,
                expected_manifest_path=manifest_path_str,
                expected_manifest_sha256=manifest_sha,
                expected_binding_digest=binding_digest,
                expected_authorization_digest=authorization["authorization_digest"],
            )
        except authz_module.FlutterExecutionAuthorizationError:
            pass
        else:
            raise AssertionError("embedded plan argv tamper accepted")


def test_verify_rejects_embedded_binding_step_id_tamper() -> None:
    authz_module = _load("p2e2a_emb_sid")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        authorization = authz_module.prepare_authorization(
            binding,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            execution_nonce=nonce,
        )
        tampered = copy.deepcopy(authorization)
        tampered["verified_binding"]["plan"]["steps"][0]["step_id"] = "tampered"
        try:
            authz_module.verify_authorization(
                tampered,
                expected_manifest_path=manifest_path_str,
                expected_manifest_sha256=manifest_sha,
                expected_binding_digest=binding_digest,
                expected_authorization_digest=authorization["authorization_digest"],
            )
        except authz_module.FlutterExecutionAuthorizationError:
            pass
        else:
            raise AssertionError("embedded step_id tamper accepted")


# ---------------------------------------------------------------------------
# 9. Step reorder/add/delete/duplicate in step_authorizations.
# ---------------------------------------------------------------------------


def test_verify_rejects_step_reorder() -> None:
    """For an operation with multiple steps (visible_codegen has 3),
    reordering step_authorizations must be rejected."""
    authz_module = _load("p2e2a_step_reorder")
    with _build_verified_binding(
        authz_module, "flutter.visible_codegen.v1", _visible_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        authorization = authz_module.prepare_authorization(
            binding,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            execution_nonce=nonce,
        )
        assert len(authorization["step_authorizations"]) >= 2
        tampered = copy.deepcopy(authorization)
        tampered["step_authorizations"][0], tampered["step_authorizations"][1] = (
            tampered["step_authorizations"][1],
            tampered["step_authorizations"][0],
        )
        try:
            authz_module.verify_authorization(
                tampered,
                expected_manifest_path=manifest_path_str,
                expected_manifest_sha256=manifest_sha,
                expected_binding_digest=binding_digest,
                expected_authorization_digest=authorization["authorization_digest"],
            )
        except authz_module.FlutterExecutionAuthorizationError:
            pass
        else:
            raise AssertionError("step reorder accepted")


def test_verify_rejects_step_add() -> None:
    authz_module = _load("p2e2a_step_add")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        authorization = authz_module.prepare_authorization(
            binding,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            execution_nonce=nonce,
        )
        tampered = copy.deepcopy(authorization)
        tampered["step_authorizations"].append(
            copy.deepcopy(tampered["step_authorizations"][0])
        )
        try:
            authz_module.verify_authorization(
                tampered,
                expected_manifest_path=manifest_path_str,
                expected_manifest_sha256=manifest_sha,
                expected_binding_digest=binding_digest,
                expected_authorization_digest=authorization["authorization_digest"],
            )
        except authz_module.FlutterExecutionAuthorizationError:
            pass
        else:
            raise AssertionError("step add accepted")


def test_verify_rejects_step_delete() -> None:
    authz_module = _load("p2e2a_step_del")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        authorization = authz_module.prepare_authorization(
            binding,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            execution_nonce=nonce,
        )
        tampered = copy.deepcopy(authorization)
        del tampered["step_authorizations"][0]
        try:
            authz_module.verify_authorization(
                tampered,
                expected_manifest_path=manifest_path_str,
                expected_manifest_sha256=manifest_sha,
                expected_binding_digest=binding_digest,
                expected_authorization_digest=authorization["authorization_digest"],
            )
        except authz_module.FlutterExecutionAuthorizationError:
            pass
        else:
            raise AssertionError("step delete accepted")


def test_verify_rejects_step_duplicate() -> None:
    authz_module = _load("p2e2a_step_dup")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        authorization = authz_module.prepare_authorization(
            binding,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            execution_nonce=nonce,
        )
        tampered = copy.deepcopy(authorization)
        tampered["step_authorizations"] = [
            copy.deepcopy(tampered["step_authorizations"][0]),
            copy.deepcopy(tampered["step_authorizations"][0]),
        ]
        try:
            authz_module.verify_authorization(
                tampered,
                expected_manifest_path=manifest_path_str,
                expected_manifest_sha256=manifest_sha,
                expected_binding_digest=binding_digest,
                expected_authorization_digest=authorization["authorization_digest"],
            )
        except authz_module.FlutterExecutionAuthorizationError:
            pass
        else:
            raise AssertionError("step duplicate accepted")


# ---------------------------------------------------------------------------
# 10-12. Per-step snapshot tampering helper.
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _prepared_fixture_authorization(authz_module_name: str):
    """Prepare a real authorization for fixture_codegen and yield
    ``(authz_module, authorization, manifest_path_str, manifest_sha,
    binding_digest)`` with the temp project / fake preflight alive."""
    authz_module = _load(authz_module_name)
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        authorization = authz_module.prepare_authorization(
            binding,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            execution_nonce=nonce,
        )
        yield authz_module, authorization, manifest_path_str, manifest_sha, binding_digest


def _assert_verify_rejects(authz_module, tampered, manifest_path_str, manifest_sha, binding_digest, expected_authz_digest) -> None:
    try:
        authz_module.verify_authorization(
            tampered,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            expected_authorization_digest=expected_authz_digest,
        )
    except authz_module.FlutterExecutionAuthorizationError:
        return
    raise AssertionError("tampered authorization accepted")


def test_verify_rejects_step_argv0_executable_path_tamper() -> None:
    with _prepared_fixture_authorization("p2e2a_argv0") as (
        authz_module, authz, mp_str, ms, bd
    ):
        tampered = copy.deepcopy(authz)
        tampered["step_authorizations"][0]["executable_path"] = "/tmp/notpython"
        _assert_verify_rejects(
            authz_module, tampered, mp_str, ms, bd, authz["authorization_digest"]
        )


def test_verify_rejects_step_argv1_primitive_path_tamper() -> None:
    with _prepared_fixture_authorization("p2e2a_argv1") as (
        authz_module, authz, mp_str, ms, bd
    ):
        tampered = copy.deepcopy(authz)
        tampered["step_authorizations"][0]["primitive_path"] = "/tmp/notprimitive.py"
        _assert_verify_rejects(
            authz_module, tampered, mp_str, ms, bd, authz["authorization_digest"]
        )


def test_verify_rejects_step_argv_digest_tamper() -> None:
    with _prepared_fixture_authorization("p2e2a_argv_d") as (
        authz_module, authz, mp_str, ms, bd
    ):
        tampered = copy.deepcopy(authz)
        tampered["step_authorizations"][0]["argv_digest"] = "0" * 64
        _assert_verify_rejects(
            authz_module, tampered, mp_str, ms, bd, authz["authorization_digest"]
        )


def test_verify_rejects_step_cwd_tamper() -> None:
    with _prepared_fixture_authorization("p2e2a_cwd_t") as (
        authz_module, authz, mp_str, ms, bd
    ):
        tampered = copy.deepcopy(authz)
        tampered["step_authorizations"][0]["cwd"] = "/tmp/tampered"
        _assert_verify_rejects(
            authz_module, tampered, mp_str, ms, bd, authz["authorization_digest"]
        )


def test_verify_rejects_step_timeout_tamper() -> None:
    with _prepared_fixture_authorization("p2e2a_to_t") as (
        authz_module, authz, mp_str, ms, bd
    ):
        tampered = copy.deepcopy(authz)
        tampered["step_authorizations"][0]["timeout_seconds"] = (
            tampered["step_authorizations"][0]["timeout_seconds"] + 1
        )
        _assert_verify_rejects(
            authz_module, tampered, mp_str, ms, bd, authz["authorization_digest"]
        )


def test_verify_rejects_step_primitive_id_tamper() -> None:
    with _prepared_fixture_authorization("p2e2a_pid_t") as (
        authz_module, authz, mp_str, ms, bd
    ):
        tampered = copy.deepcopy(authz)
        tampered["step_authorizations"][0]["primitive"] = "not_a_real_primitive.py"
        _assert_verify_rejects(
            authz_module, tampered, mp_str, ms, bd, authz["authorization_digest"]
        )


def test_verify_rejects_step_primitive_path_tamper_via_recompute() -> None:
    """Coordinated: attacker changes primitive_path AND recomputes the
    step digest AND the top-level digest AND supplies the matching
    expected digest. Verify must still reject because primitive_path is
    not the canonical path of argv[1] in the embedded binding."""
    with _prepared_fixture_authorization("p2e2a_prim_path_coordinated") as (
        authz_module, authz, mp_str, ms, bd
    ):
        tampered = copy.deepcopy(authz)
        tampered["step_authorizations"][0]["primitive_path"] = "/tmp/notprimitive.py"
        sa = tampered["step_authorizations"][0]
        sa_payload = {k: v for k, v in sa.items() if k != "step_authorization_digest"}
        sa["step_authorization_digest"] = hashlib.sha256(
            _canonical_compact(sa_payload)
        ).hexdigest()
        top_payload = {
            k: v for k, v in tampered.items() if k != "authorization_digest"
        }
        tampered["authorization_digest"] = hashlib.sha256(
            _canonical_compact(top_payload)
        ).hexdigest()
        _assert_verify_rejects(
            authz_module, tampered, mp_str, ms, bd, tampered["authorization_digest"]
        )


def test_verify_rejects_step_primitive_sha_tamper() -> None:
    with _prepared_fixture_authorization("p2e2a_psha_t") as (
        authz_module, authz, mp_str, ms, bd
    ):
        tampered = copy.deepcopy(authz)
        tampered["step_authorizations"][0]["primitive_sha256"] = "9" * 64
        _assert_verify_rejects(
            authz_module, tampered, mp_str, ms, bd, authz["authorization_digest"]
        )


def test_verify_rejects_step_executable_sha_tamper() -> None:
    with _prepared_fixture_authorization("p2e2a_esha_t") as (
        authz_module, authz, mp_str, ms, bd
    ):
        tampered = copy.deepcopy(authz)
        tampered["step_authorizations"][0]["executable_sha256"] = "9" * 64
        _assert_verify_rejects(
            authz_module, tampered, mp_str, ms, bd, authz["authorization_digest"]
        )


def test_verify_rejects_coordinated_executable_sha_tamper() -> None:
    """Coordinated: attacker changes executable_sha256 AND recomputes
    step + top digests AND supplies the matching expected digest.
    Verify must still fail because the recorded executable_sha256 does
    not equal the current sys.executable bytes hash."""
    with _prepared_fixture_authorization("p2e2a_esha_coordinated") as (
        authz_module, authz, mp_str, ms, bd
    ):
        tampered = copy.deepcopy(authz)
        tampered["step_authorizations"][0]["executable_sha256"] = "9" * 64
        sa = tampered["step_authorizations"][0]
        sa_payload = {k: v for k, v in sa.items() if k != "step_authorization_digest"}
        sa["step_authorization_digest"] = hashlib.sha256(
            _canonical_compact(sa_payload)
        ).hexdigest()
        top_payload = {
            k: v for k, v in tampered.items() if k != "authorization_digest"
        }
        tampered["authorization_digest"] = hashlib.sha256(
            _canonical_compact(top_payload)
        ).hexdigest()
        _assert_verify_rejects(
            authz_module, tampered, mp_str, ms, bd, tampered["authorization_digest"]
        )


def test_verify_rejects_step_authorization_digest_tamper() -> None:
    with _prepared_fixture_authorization("p2e2a_sd_t") as (
        authz_module, authz, mp_str, ms, bd
    ):
        tampered = copy.deepcopy(authz)
        tampered["step_authorizations"][0]["step_authorization_digest"] = "1" * 64
        _assert_verify_rejects(
            authz_module, tampered, mp_str, ms, bd, authz["authorization_digest"]
        )


# ---------------------------------------------------------------------------
# 13. Non-canonical / symlink / missing / non-file executable or script
#     cases tested without modifying protected files.
# ---------------------------------------------------------------------------


def test_helper_bind_current_executable_rejects_lexical_mismatch() -> None:
    """The per-step authorization's own fail-closed branch: argv[0] that
    does not lexically equal the current interpreter is rejected."""
    authz_module = _load("p2e2a_helper_lex")
    try:
        authz_module._bind_current_executable("/usr/local/bin/python3")
    except authz_module.FlutterExecutionAuthorizationError:
        return
    raise AssertionError("lexical mismatch accepted")


def test_helper_bind_current_executable_rejects_non_string() -> None:
    authz_module = _load("p2e2a_helper_nstr")
    for bad in (None, 42, b"/usr/bin/python3", []):
        try:
            authz_module._bind_current_executable(bad)
        except authz_module.FlutterExecutionAuthorizationError:
            continue
        raise AssertionError(f"non-string argv[0] accepted: {bad!r}")


def test_helper_bind_current_executable_rejects_missing() -> None:
    """The fail-closed branch for a missing canonical executable path."""
    authz_module = _load("p2e2a_helper_missing")
    saved = authz_module._current_executable
    authz_module._current_executable = lambda: "/definitely/does/not/exist/python"
    try:
        try:
            authz_module._bind_current_executable("/definitely/does/not/exist/python")
        except authz_module.FlutterExecutionAuthorizationError:
            return
        raise AssertionError("missing executable accepted")
    finally:
        authz_module._current_executable = saved


def test_helper_bind_current_executable_rejects_directory() -> None:
    """The fail-closed branch for an executable path that is a
    directory."""
    authz_module = _load("p2e2a_helper_dir")
    with _canonical_tempdir() as tmp:
        d = tmp / "i_am_a_dir"
        d.mkdir()
        saved = authz_module._current_executable
        authz_module._current_executable = lambda: str(d)
        try:
            try:
                authz_module._bind_current_executable(str(d))
            except authz_module.FlutterExecutionAuthorizationError:
                return
            raise AssertionError("directory executable accepted")
        finally:
            authz_module._current_executable = saved


def test_helper_bind_current_executable_rejects_symlink_to_different_file() -> None:
    """argv[0] is a symlink to a different file than the current
    interpreter. The lexical equality check (argv[0] != sys.executable)
    rejects this: a substituted symlink is never the current
    interpreter's lexical path. (In production the module never patches
    ``_current_executable``; this test exercises the unpatched lexical
    defence directly.)"""
    authz_module = _load("p2e2a_helper_sym")
    with _canonical_tempdir() as tmp:
        other = tmp / "other.bin"
        other.write_bytes(b"not the interpreter")
        link = tmp / "py_link"
        os.symlink(other, link)
        try:
            authz_module._bind_current_executable(str(link))
        except authz_module.FlutterExecutionAuthorizationError:
            return
        raise AssertionError("symlink-to-different-file accepted")


def test_helper_bind_primitive_script_rejects_symlink() -> None:
    """The per-step authorization's own fail-closed branch for a
    primitive script argv[1] that is a symlink (the documented
    symlink-rejection case). Tested by calling the helper directly so
    it does not depend on verify_binding catching the tamper first."""
    authz_module = _load("p2e2a_helper_prim_sym")
    with _canonical_tempdir() as tmp:
        real = tmp / "real_prim.py"
        real.write_bytes(b"#!/usr/bin/env python3\n# real primitive\n")
        expected_sha = hashlib.sha256(real.read_bytes()).hexdigest()
        link = tmp / "linked_prim.py"
        os.symlink(real, link)
        try:
            authz_module._bind_primitive_script(
                str(link), "linked_prim.py", expected_sha
            )
        except authz_module.FlutterExecutionAuthorizationError:
            return
        raise AssertionError("symlinked primitive script accepted")


def test_helper_bind_primitive_script_rejects_missing() -> None:
    authz_module = _load("p2e2a_helper_prim_missing")
    try:
        authz_module._bind_primitive_script(
            "/definitely/does/not/exist/prim.py", "prim.py", "0" * 64
        )
    except authz_module.FlutterExecutionAuthorizationError:
        return
    raise AssertionError("missing primitive script accepted")


def test_helper_bind_primitive_script_rejects_directory() -> None:
    authz_module = _load("p2e2a_helper_prim_dir")
    with _canonical_tempdir() as tmp:
        d = tmp / "i_am_a_dir"
        d.mkdir()
        try:
            authz_module._bind_primitive_script(str(d), "idir", "0" * 64)
        except authz_module.FlutterExecutionAuthorizationError:
            return
        raise AssertionError("directory primitive script accepted")


def test_helper_bind_primitive_script_rejects_sha_drift() -> None:
    """The fail-closed branch for digest drift between the recorded
    primitive_sha256 and the current script bytes."""
    authz_module = _load("p2e2a_helper_prim_drift")
    with _canonical_tempdir() as tmp:
        real = tmp / "real_prim.py"
        real.write_bytes(b"#!/usr/bin/env python3\n# real primitive\n")
        wrong_sha = "0" * 64
        try:
            authz_module._bind_primitive_script(
                str(real), "real_prim.py", wrong_sha
            )
        except authz_module.FlutterExecutionAuthorizationError:
            return
        raise AssertionError("sha drift accepted")


def test_verify_rejects_primitive_script_symlink_via_public_api() -> None:
    """Public-API path: a binding whose argv[1] is a symlink is
    rejected. The per-step authorization's _bind_primitive_script
    helper has its own symlink-rejection branch (covered directly
    above); through the public API the binding's verify_binding also
    rejects the tamper first (rebuilt argv[1] is the canonical capsule
    script, candidate argv[1] is the symlink). Either way the slice
    fails closed."""
    authz_module = _load("p2e2a_prim_sym_pub")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        binding = copy.deepcopy(binding)
        with _canonical_tempdir() as tmp:
            real_script = Path(binding["plan"]["steps"][0]["argv"][1])
            link = tmp / "linked_prim.py"
            os.symlink(real_script, link)
            binding["plan"]["steps"][0]["argv"][1] = str(link)
            manifest_path_str, manifest_sha, binding_digest, nonce = expected
            try:
                authz_module.prepare_authorization(
                    binding,
                    expected_manifest_path=manifest_path_str,
                    expected_manifest_sha256=manifest_sha,
                    expected_binding_digest=binding_digest,
                    execution_nonce=nonce,
                )
            except authz_module.FlutterExecutionAuthorizationError:
                pass
            else:
                raise AssertionError("symlinked primitive script accepted via public API")


# ---------------------------------------------------------------------------
# 14. No project/state/run-root writes during prepare or verify.
# ---------------------------------------------------------------------------


def _snapshot(root: Path) -> dict[Path, bytes]:
    snap: dict[Path, bytes] = {}
    for p in sorted(root.rglob("*")):
        if p.is_dir():
            continue
        if p.is_symlink():
            snap[p] = b"<symlink>"
        else:
            snap[p] = p.read_bytes()
    return snap


def test_prepare_does_not_mutate_project_or_run_root() -> None:
    authz_module = _load("p2e2a_no_write_prep")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        before_proj = _snapshot(proj)
        before_spec = _snapshot(spec)
        authz_module.prepare_authorization(
            binding,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            execution_nonce=nonce,
        )
        after_proj = _snapshot(proj)
        after_spec = _snapshot(spec)
    assert set(before_proj.keys()) == set(after_proj.keys())
    for p, data in before_proj.items():
        assert after_proj[p] == data, f"project mutated: {p}"
    assert set(before_spec.keys()) == set(after_spec.keys())
    for p, data in before_spec.items():
        assert after_spec[p] == data, f"run root mutated: {p}"


def test_verify_does_not_mutate_project_or_run_root() -> None:
    authz_module = _load("p2e2a_no_write_verify")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        authorization = authz_module.prepare_authorization(
            binding,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            execution_nonce=nonce,
        )
        before_proj = _snapshot(proj)
        before_spec = _snapshot(spec)
        authz_module.verify_authorization(
            authorization,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            expected_authorization_digest=authorization["authorization_digest"],
        )
        after_proj = _snapshot(proj)
        after_spec = _snapshot(spec)
    assert set(before_proj.keys()) == set(after_proj.keys())
    for p, data in before_proj.items():
        assert after_proj[p] == data, f"project mutated: {p}"
    assert set(before_spec.keys()) == set(after_spec.keys())
    for p, data in before_spec.items():
        assert after_spec[p] == data, f"run root mutated: {p}"


def test_prepare_does_not_mutate_descriptor_or_capsule_or_registry() -> None:
    authz_module = _load("p2e2a_no_write_prod_prep")
    before_reg = REGISTRY_PATH.read_bytes()
    before_desc = DESCRIPTOR_PATH.read_bytes()
    before_capsule = MANIFEST_PATH.read_bytes()
    before_skill = SKILL_MD_PATH.read_bytes()
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        authz_module.prepare_authorization(
            binding,
            expected_manifest_path=manifest_path_str,
            expected_manifest_sha256=manifest_sha,
            expected_binding_digest=binding_digest,
            execution_nonce=nonce,
        )
    assert REGISTRY_PATH.read_bytes() == before_reg
    assert DESCRIPTOR_PATH.read_bytes() == before_desc
    assert MANIFEST_PATH.read_bytes() == before_capsule
    assert SKILL_MD_PATH.read_bytes() == before_skill


# ---------------------------------------------------------------------------
# 15. AST/static guard on the production module source.
# ---------------------------------------------------------------------------


_FORBIDDEN_IMPORTS = frozenset(
    {
        "subprocess",
        "socket",
        "socketserver",
        "ssl",
        "urllib",
        "http",
        "requests",
        "ftplib",
        "telnetlib",
        "smtplib",
        "xmlrpc",
        "asyncio",
    }
)

_FORBIDDEN_ATTRS = frozenset(
    {
        "system",
        "popen",
        "spawnl",
        "spawnle",
        "spawnlp",
        "spawnlpe",
        "spawnv",
        "spawnve",
        "spawnvp",
        "spawnvpe",
        "execl",
        "execle",
        "execlp",
        "execlpe",
        "execv",
        "execve",
        "execvp",
        "execvpe",
        "fork",
        "write",
        "write_text",
        "write_bytes",
        "mkdir",
        "makedirs",
        "rmdir",
        "unlink",
        "remove",
        "rename",
        "replace",
        "touch",
        "chmod",
        "chown",
        "lchmod",
        "lchown",
        "symlink",
        "symlink_to",
        "hardlink_to",
        "link",
        "truncate",
        "putenv",
        "setuid",
        "setgid",
        "seteuid",
        "setegid",
    }
)


def _walk_forbidden(node, errors, role):
    if isinstance(node, ast.Import):
        for alias in node.names:
            top = alias.name.split(".")[0]
            if top in _FORBIDDEN_IMPORTS:
                errors.append(f"{role}: forbidden import {alias.name}")
    elif isinstance(node, ast.ImportFrom):
        if node.module is not None:
            top = node.module.split(".")[0]
            if top in _FORBIDDEN_IMPORTS:
                errors.append(f"{role}: forbidden import-from {node.module}")
    if isinstance(node, ast.Attribute):
        if node.attr in _FORBIDDEN_ATTRS:
            errors.append(f"{role}: forbidden attribute {node.attr}")
    if isinstance(node, ast.Call):
        for kw in node.keywords:
            if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                errors.append(f"{role}: forbidden shell=True")
            if kw.arg == "mode" and isinstance(kw.value, ast.Constant) and (
                "w" in str(kw.value.value) or "a" in str(kw.value.value) or "+" in str(kw.value.value)
            ):
                errors.append(f"{role}: forbidden open mode {kw.value.value!r}")
    for child in ast.iter_child_nodes(node):
        _walk_forbidden(child, errors, role)


def _strip_docstrings(tree: ast.AST) -> str:
    """Return a source-code reconstruction with module/class/function
    docstrings replaced by ``pass``, so coarse plain-text guards do
    not false-positive on docstring text such as "never uses
    ``shell=True``"."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if not body:
                continue
            first = body[0]
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                # Replace the docstring expression with a ``pass``.
                body[0] = ast.Pass(
                    lineno=getattr(first, "lineno", 1),
                    col_offset=getattr(first, "col_offset", 0),
                )
    try:
        return ast.unparse(tree)
    except Exception:  # pragma: no cover - ast.unparse is always available on 3.9+
        return ""


def _assert_no_forbidden_surface(source: str, *, role: Path) -> None:
    tree = ast.parse(source, filename=str(role))
    errors: list[str] = []
    _walk_forbidden(tree, errors, role)
    # Apply the coarse plain-text guards only to code (docstrings
    # stripped) so a truthful docstring that mentions ``shell=True`` or
    # ``import subprocess`` as the prohibited surface does not trip the
    # guard.
    code_only = _strip_docstrings(tree)
    for needle in ("import subprocess", "import socket", "import urllib",
                   "shell=True", "os.system", "os.popen"):
        assert needle not in code_only, needle
    assert errors == [], f"forbidden surface in {role}: {errors}"


def test_static_guard_no_subprocess() -> None:
    source = AUTHZ_PATH.read_text()
    _assert_no_forbidden_surface(source, role=AUTHZ_PATH)


def test_static_guard_no_network() -> None:
    source = AUTHZ_PATH.read_text()
    for forbidden in ("socket", "urllib", "requests", "http.client", "ftplib"):
        assert f"import {forbidden}" not in source, forbidden


def test_static_guard_no_write_or_shell() -> None:
    source = AUTHZ_PATH.read_text()
    tree = ast.parse(source, filename=str(AUTHZ_PATH))
    errors: list[str] = []
    _walk_forbidden(tree, errors, AUTHZ_PATH)
    assert errors == [], errors


def test_static_guard_no_open_write_mode() -> None:
    source = AUTHZ_PATH.read_text()
    tree = ast.parse(source, filename=str(AUTHZ_PATH))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                    mode = str(kw.value.value)
                    assert not any(c in mode for c in "wa+"), mode


# Attributes that perform real filesystem I/O at call time and must
# therefore never appear in a top-level (import-time) RHS expression.
# This is a tighter check than the AST guard for the *module body*
# generally: even one ``Path.resolve()`` or ``.read_bytes()`` in a
# top-level assignment makes the import perform real I/O.
_FORBIDDEN_IO_ATTRS = frozenset(
    {
        # path resolution / stat
        "resolve",
        "stat",
        "lstat",
        # reads
        "read_bytes",
        "read_text",
        "read",
        "readline",
        "readlines",
        # directory scans
        "iterdir",
        "glob",
        "rglob",
        "scandir",
        "listdir",
        "walk",
        # writes / mutation
        "write",
        "write_text",
        "write_bytes",
        "mkdir",
        "makedirs",
        "rmdir",
        "unlink",
        "remove",
        "rename",
        "replace",
        "touch",
        "chmod",
        "chown",
        "lchmod",
        "lchown",
        "symlink",
        "symlink_to",
        "hardlink_to",
        "link",
        "truncate",
        # exec/spawn
        "system",
        "popen",
        "execl",
        "execle",
        "execlp",
        "execlpe",
        "execv",
        "execve",
        "execvp",
        "execvpe",
        "fork",
    }
)

# Bare-name calls (``open(...)``, ``execfile(...)``) forbidden at
# import time.
_FORBIDDEN_IO_BARENAMES = frozenset(
    {
        "open",
        "execfile",
        "exec_module",
        "input",
    }
)

# Attribute / module-qualified calls permitted at import time even
# though they look like calls. These are pure constructors and lexical
# transforms only.
_PERMITTED_IO_ATTRS = frozenset(
    {
        # Pure constructors / lexical transforms.
        "Path",
        "abspath",
        "dirname",
        "join",
        "normpath",
        "basename",
        "split",
        "splitext",
        "relpath",
        "compile",  # re.compile is pure
        "frozenset",
        "set",
        "dict",
        "list",
        "tuple",
        "len",
        "hex",
        "Pattern",
    }
)


def _attr_chain(node: ast.AST) -> str:
    """Render ``a.b.c`` for an Attribute/Name expression, '' if mixed."""
    parts: list[str] = []
    cur: ast.AST = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    else:
        return ""
    return ".".join(reversed(parts))


def _is_permitted_call(node: ast.Call) -> bool:
    """True iff ``node`` is a call explicitly permitted at import time
    (pure constructor or lexical transform)."""
    func = node.func
    if isinstance(func, ast.Attribute):
        if func.attr in _PERMITTED_IO_ATTRS:
            return True
        # ``Path(__file__).parent`` / ``.parents[..]`` are attribute
        # accesses (not calls); only Call nodes reach here.
        return False
    if isinstance(func, ast.Name):
        if func.id in _PERMITTED_IO_ATTRS:
            return True
        return False
    return False


def _scan_import_time_calls(node: ast.AST, errors: list[str]) -> None:
    """Walk ``node`` and flag any forbidden import-time Call/Attribute."""
    # Attribute references that *are* calls? No; only Call performs I/O.
    # But ``Path(__file__).resolve()`` is a Call whose func is an
    # Attribute with attr 'resolve'.
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Attribute):
                if func.attr in _FORBIDDEN_IO_ATTRS:
                    errors.append(
                        f"import-time I/O call: {func.attr} at line "
                        f"{getattr(child, 'lineno', '?')}"
                    )
                    continue
                if func.attr in _PERMITTED_IO_ATTRS:
                    continue
                # Unknown attribute call: permit but record for the
                # attribute-name check below only if it actually
                # performs I/O. We do not reject unknown attribute
                # calls because e.g. ``frozenset({...})`` is fine.
            elif isinstance(func, ast.Name):
                if func.id in _FORBIDDEN_IO_BARENAMES:
                    errors.append(
                        f"import-time I/O call: {func.id} at line "
                        f"{getattr(child, 'lineno', '?')}"
                    )
                    continue
                if func.id in _PERMITTED_IO_ATTRS:
                    continue
            else:
                # Subscript / lambda / etc. call: conservatively
                # flag (these do not appear in the current module).
                errors.append(
                    f"import-time indirect call: {_attr_chain(func)!r} "
                    f"at line {getattr(child, 'lineno', '?')}"
                )


def test_static_guard_import_time_io() -> None:
    """No filesystem-I/O call anywhere in a top-level (module-body)
    Assign / AnnAssign / Expr RHS. Pure constructors and lexical
    transforms (``Path(...)``, ``os.path.abspath``, ``os.path.dirname``,
    ``os.path.join``, ``re.compile``, ``frozenset``) are permitted.

    A top-level ``Path(__file__).resolve().parent`` previously slipped
    through the weaker check that only inspected whether the *top-level
    statement node itself* was an ``ast.Call``. The strengthened check
    walks the full RHS expression tree and rejects the real
    ``Path.resolve`` filesystem-resolution call."""
    source = AUTHZ_PATH.read_text()
    tree = ast.parse(source, filename=str(AUTHZ_PATH))
    errors: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.With, ast.AsyncWith)):
            errors.append(
                f"import-time with-block at module top level: "
                f"line {getattr(node, 'lineno', '?')}"
            )
            continue
        rhs: ast.AST | None = None
        if isinstance(node, ast.Assign):
            rhs = node.value
        elif isinstance(node, ast.AnnAssign):
            rhs = node.value
        elif isinstance(node, ast.Expr):
            rhs = node.value
        elif isinstance(node, (ast.Import, ast.ImportFrom, ast.ClassDef,
                               ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.If, ast.For, ast.While, ast.Try,
                               ast.Raise, ast.Assert, ast.Global,
                               ast.Nonlocal, ast.Delete, ast.Pass,
                               ast.AugAssign)):
            # Module-level class/function defs and control flow are
            # not import-time I/O surfaces (their *bodies* run lazily).
            # The general AST guard (test_static_guard_no_subprocess /
            # test_static_guard_no_write_or_shell) covers the rest.
            continue
        if rhs is None:
            continue
        # Reject any direct top-level Call that is not permitted, then
        # walk the RHS expression tree for nested forbidden calls.
        if isinstance(rhs, ast.Call) and not _is_permitted_call(rhs):
            errors.append(
                f"import-time direct call at module top level: "
                f"{ast.dump(rhs)} line {getattr(rhs, 'lineno', '?')}"
            )
        _scan_import_time_calls(rhs, errors)
    assert errors == [], (
        f"import-time I/O surface in {AUTHZ_PATH}: {errors}"
    )


# ---------------------------------------------------------------------------
# 15b. Truthful process/I/O contract: the new module's public APIs
# deliberately re-attest the embedded binding through
# ``flutter_execution_binding_v1.verify_binding``, which re-runs the
# fixed read-only ``flutter --version --machine`` preflight (a real
# child process with ``shell=False``). The module must not overclaim
# "no command is executed" / "never spawns a process" / unqualified
# "no execution".
# ---------------------------------------------------------------------------


def test_contract_states_transitive_preflight_boundary() -> None:
    """The module docstring AND the SKILL.md P2e2a section must both
    state, truthfully, that prepare/verify transitively re-run the
    fixed read-only Flutter version preflight through the shared
    binding verifier, AND must NOT carry the false unqualified claims
    listed below.

    'Unqualified' is detected with a word-boundary regex: the false
    claim 'never spawns a process' followed by a non-word character
    (period, comma, semicolon, end-of-string) is rejected, while the
    truthful narrower 'never directly spawns a process' is permitted
    because 'directly' / '*directly*' is a word/qualifier continuing
    the phrase.

    For SKILL.md the contract is scoped to the P2e2a section
    (between the '## P2e2a' header and the next '## ' header), so
    correct statements about other slices (e.g. the P2d2 registry
    correctly never executing a subprocess) are not flagged."""
    module_src = AUTHZ_PATH.read_text()
    full_skill = SKILL_MD_PATH.read_text()

    # Extract the P2e2a section from SKILL.md.
    skill_lines = full_skill.splitlines()
    start = end = None
    for i, line in enumerate(skill_lines):
        if line.startswith("## P2e2a"):
            start = i
        elif start is not None and line.startswith("## "):
            end = i
            break
    assert start is not None, "P2e2a section not found in SKILL.md"
    if end is None:
        end = len(skill_lines)
    # Also include the P2e2a boundaries bullet (in the Boundaries
    # section, which mentions P2e2a by name) so the truthful wording
    # there is enforced too. Concatenate the P2e2a section and any
    # boundaries bullet that mentions 'P2e2a'.
    boundaries_lines = []
    in_boundaries = False
    for line in skill_lines:
        if line.startswith("## Boundaries"):
            in_boundaries = True
            continue
        if in_boundaries and line.startswith("## "):
            in_boundaries = False
        if in_boundaries and "P2e2a" in line:
            boundaries_lines.append(line)
    skill_src = "\n".join(skill_lines[start:end]) + "\n" + "\n".join(boundaries_lines)

    # False unqualified claims that must NOT appear in either source.
    # Each entry is compiled with a trailing word-boundary anchor so a
    # truthful qualifier (e.g. 'directly') defeats the match.
    false_claim_patterns = [
        re.compile(r"no command is executed\b", re.IGNORECASE),
        re.compile(r"never spawns a process(?!\s+\w|\s+\*directly)", re.IGNORECASE),
        re.compile(r"never executes a subprocess\b", re.IGNORECASE),
        re.compile(r"performs no execution\b", re.IGNORECASE),
        re.compile(r"performs \*\*no execution\*\*", re.IGNORECASE),
    ]
    for src, role in ((module_src, AUTHZ_PATH), (skill_src, "SKILL.md P2e2a section")):
        for pat in false_claim_patterns:
            m = pat.search(src)
            assert m is None, (
                f"{role}: false unqualified claim present: {m.group(0)!r} "
                f"(pattern {pat.pattern!r})"
            )

    # Required truthful statements. At least one formulation of each
    # must appear in BOTH the module docstring and the SKILL P2e2a
    # section. The transitive-preflight requirement is satisfied if
    # both ``--version`` and ``--machine`` appear (they may be
    # separated by `", "` in the rendered argv list, so a single
    # substring match is too strict).
    required_phrases = (
        "transitive",
        "preflight",
    )
    for src, role in ((module_src, AUTHZ_PATH), (skill_src, "SKILL.md P2e2a section")):
        lower = src.lower()
        for needle in required_phrases:
            assert needle.lower() in lower, (
                f"{role}: required truthful phrase missing: {needle!r}"
            )
        assert "--version" in lower, (
            f"{role}: required truthful phrase missing: '--version'"
        )
        assert "--machine" in lower, (
            f"{role}: required truthful phrase missing: '--machine'"
        )

    # The module must clearly state that no *operation-plan* command is
    # executed (the truthful narrower claim).
    assert "operation-plan" in module_src.lower(), (
        f"{AUTHZ_PATH}: must state 'operation-plan' boundary"
    )
    assert "operation-plan" in skill_src.lower(), (
        "SKILL.md P2e2a section: must state 'operation-plan' boundary"
    )


# ---------------------------------------------------------------------------
# 16. Malformed JSON-safe values, bool-as-int, NaN/Infinity.
# ---------------------------------------------------------------------------


def test_prepare_rejects_authorization_with_nan_in_binding() -> None:
    """A binding carrying NaN/Infinity somewhere is not canonical-JSON
    safe and must be rejected."""
    authz_module = _load("p2e2a_nan")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        tampered_binding = copy.deepcopy(binding)
        tampered_binding["request"]["feature_id"] = float("nan")
        try:
            authz_module.prepare_authorization(
                tampered_binding,
                expected_manifest_path=manifest_path_str,
                expected_manifest_sha256=manifest_sha,
                expected_binding_digest=binding_digest,
                execution_nonce=nonce,
            )
        except authz_module.FlutterExecutionAuthorizationError:
            pass
        else:
            raise AssertionError("NaN-bearing binding accepted")


def test_verify_rejects_step_timeout_bool() -> None:
    with _prepared_fixture_authorization("p2e2a_bool_to") as (
        authz_module, authz, mp_str, ms, bd
    ):
        tampered = copy.deepcopy(authz)
        tampered["step_authorizations"][0]["timeout_seconds"] = True
        _assert_verify_rejects(
            authz_module, tampered, mp_str, ms, bd, authz["authorization_digest"]
        )


def test_verify_rejects_step_timeout_nan_value() -> None:
    """A non-JSON-safe value in the embedded verified binding must be
    rejected."""
    with _prepared_fixture_authorization("p2e2a_nan_to") as (
        authz_module, authz, mp_str, ms, bd
    ):
        tampered = copy.deepcopy(authz)
        tampered["verified_binding"]["request"]["feature_id"] = float("nan")
        _assert_verify_rejects(
            authz_module, tampered, mp_str, ms, bd, authz["authorization_digest"]
        )


def test_verify_rejects_non_dict_authorization() -> None:
    authz_module = _load("p2e2a_nondict")
    for cand in ([], "string", 42, None, b"bytes"):
        try:
            authz_module.verify_authorization(
                cand,
                expected_manifest_path="/x",
                expected_manifest_sha256="0" * 64,
                expected_binding_digest="0" * 64,
                expected_authorization_digest="0" * 64,
            )
        except authz_module.FlutterExecutionAuthorizationError:
            pass
        else:
            raise AssertionError(f"non-dict authorization accepted: {cand!r}")


def test_verify_rejects_non_dict_binding() -> None:
    authz_module = _load("p2e2a_nondict_binding")
    for cand in ([], "string", 42, None):
        try:
            authz_module.prepare_authorization(
                cand,
                expected_manifest_path="/x",
                expected_manifest_sha256="0" * 64,
                expected_binding_digest="0" * 64,
                execution_nonce="0" * 32,
            )
        except authz_module.FlutterExecutionAuthorizationError:
            pass
        else:
            raise AssertionError(f"non-dict binding accepted: {cand!r}")


def test_prepare_rejects_non_string_expected_manifest_path() -> None:
    authz_module = _load("p2e2a_path_type")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        for bad in (None, 42, b"/x", [], {}):
            try:
                authz_module.prepare_authorization(
                    binding,
                    expected_manifest_path=bad,
                    expected_manifest_sha256=manifest_sha,
                    expected_binding_digest=binding_digest,
                    execution_nonce=nonce,
                )
            except authz_module.FlutterExecutionAuthorizationError:
                pass
            else:
                raise AssertionError(f"non-string manifest path accepted: {bad!r}")


def test_prepare_rejects_malformed_expected_sha() -> None:
    authz_module = _load("p2e2a_sha_mal")
    with _build_verified_binding(
        authz_module, "flutter.fixture_codegen.v1", _fixture_request
    ) as (binding_module, binding, mp, proj, spec, expected):
        manifest_path_str, manifest_sha, binding_digest, nonce = expected
        for bad in ("XYZ", "0" * 63, "0" * 65, "G" * 64, 123, None, b"0" * 64):
            try:
                authz_module.prepare_authorization(
                    binding,
                    expected_manifest_path=manifest_path_str,
                    expected_manifest_sha256=bad,
                    expected_binding_digest=binding_digest,
                    execution_nonce=nonce,
                )
            except authz_module.FlutterExecutionAuthorizationError:
                pass
            else:
                raise AssertionError(f"malformed manifest sha accepted: {bad!r}")


# ---------------------------------------------------------------------------
# 17. Producer and verifier continue rejecting trailing-newline batch_id.
# ---------------------------------------------------------------------------


def test_producer_rejects_trailing_newline_batch_id() -> None:
    freeze = _load_freeze("p2e2a_freeze_nl")
    common = _load_common("p2e2a_common_nl")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        proj.mkdir()
        _build_minimal_flutter_project(proj)
        try:
            freeze.freeze_selection_manifest(
                resolved_config=_resolved(proj),
                candidates=_good_cands(),
                batch_id="bad_batch\n",
                registries=common.load_registries(),
            )
        except Exception:
            pass
        else:
            raise AssertionError("trailing-newline batch_id accepted by producer")


def test_verifier_rejects_trailing_newline_batch_id() -> None:
    freeze = _load_freeze("p2e2a_freeze_ver_nl")
    common = _load_common("p2e2a_common_ver_nl")
    verify_sel = _load("p2e2a_sel_verify_nl", VERIFY_SEL_PATH)
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        proj.mkdir()
        _build_minimal_flutter_project(proj)
        ack = freeze.freeze_selection_manifest(
            resolved_config=_resolved(proj),
            candidates=_good_cands(),
            batch_id="good_batch",
            registries=common.load_registries(),
        )
        mp = Path(ack["manifest_path"])
        raw = mp.read_bytes()
        doc = json.loads(raw)
        doc["batch_id"] = "good_batch\n"
        tampered_bytes = (
            json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        mp.write_bytes(tampered_bytes)
        try:
            verify_sel.verify(mp)
        except verify_sel.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("trailing-newline batch_id accepted by verifier")


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
