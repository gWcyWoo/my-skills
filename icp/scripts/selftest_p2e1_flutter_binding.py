#!/usr/bin/env python3
"""Vertical RED -> GREEN selftest for the ICP P2e1 Flutter
non-executable execution binding
(``platforms/flutter_execution_binding_v1``).

The binding re-attests the current selection manifest, vendored
capsule, Flutter descriptor, project preflight, exact operation
request, rebuilt plan, and source digests, then emits a
deterministic ``icp.flutter-execution-binding.v1`` document.
``verify_binding()`` re-runs the full preparation chain and requires
exact equality with the candidate binding. The slice is
**non-executable**: no plan is executed, ``executable`` is always
``False``, ``activation_state`` is always ``inactive``, and the
binding module never imports ``subprocess``.

Tests use temporary canonical Flutter project/run roots and the real
operation builder. The fixed Flutter project preflight call is
stubbed in-process to avoid relying on a host Flutter installation;
no production injection hook is added. No production file (capsule,
descriptor, manifest, registry, ``iff/**``, existing project files)
is mutated.

Run directly:

    PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p2e1_flutter_binding.py
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import inspect
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
ICP_ROOT = Path(__file__).resolve().parents[1]
ICP_SCRIPTS = Path(__file__).resolve().parent
PLATFORMS_DIR = ICP_SCRIPTS / "platforms"
BINDING_PATH = PLATFORMS_DIR / "flutter_execution_binding_v1.py"
FREEZE_PATH = ICP_SCRIPTS / "freeze_selection_manifest.py"
COMMON_PATH = ICP_SCRIPTS / "icp_common.py"
VERIFY_SEL_PATH = ICP_SCRIPTS / "verify_selection_manifest_v1.py"
PREFLIGHT_PATH = PLATFORMS_DIR / "flutter_project_preflight_v1.py"
DESCRIPTOR_PATH = PLATFORMS_DIR / "flutter_standard_v1.py"
OPERATIONS_PATH = PLATFORMS_DIR / "flutter_operations_v1.py"
MANIFEST_PATH = ICP_ROOT / "references" / "baselines" / "iff-v1-vendor.json"
REGISTRY_PATH = ICP_ROOT / "references" / "registries.json"
SKILL_MD_PATH = ICP_ROOT / "SKILL.md"

KIND_BINDING = "icp.flutter-execution-binding.v1"
KIND_VERIFY = "icp.flutter-execution-binding-verify.v1"
SCHEMA_VERSION = 1

OPERATION_IDS = (
    "flutter.visible_codegen.v1",
    "flutter.fixture_codegen.v1",
    "flutter.trace_harness.v1",
    "flutter.packaging.v1",
    "flutter.test_runner.v1",
    "flutter.runtime_capture.v1",
    "flutter.project_gates.v1",
    "flutter.fan_in.v1",
)

# Fixed private mapping plan_id -> descriptor port id.
PORT_FOR_OPERATION = {
    "flutter.visible_codegen.v1": "visible_codegen",
    "flutter.fixture_codegen.v1": "fixture_codegen",
    "flutter.trace_harness.v1": "trace_harness",
    "flutter.packaging.v1": "packaging",
    "flutter.test_runner.v1": "test_runner",
    "flutter.runtime_capture.v1": "runtime_capture",
    "flutter.project_gates.v1": "project_gates",
    "flutter.fan_in.v1": "fan_in",
}

CAPABILITY_FOR_OPERATION = {
    "flutter.visible_codegen.v1": "required",
    "flutter.fixture_codegen.v1": "required",
    "flutter.trace_harness.v1": "optional-with-shared-policy",
    "flutter.packaging.v1": "required",
    "flutter.test_runner.v1": "required",
    "flutter.runtime_capture.v1": "optional-with-shared-policy",
    "flutter.project_gates.v1": "required",
    "flutter.fan_in.v1": "required",
}


# ---------------------------------------------------------------------------
# Module loaders.
# ---------------------------------------------------------------------------


def _load(name: str, path: Path = BINDING_PATH):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_freeze(name: str = "p2e1_fb_freeze"):
    return _load(name, FREEZE_PATH)


def _load_common(name: str = "p2e1_fb_common"):
    return _load(name, COMMON_PATH)


def _canonical_json(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _is_sha256_hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value.islower()
        and all(c in "0123456789abcdef" for c in value)
    )


@contextlib.contextmanager
def _canonical_tempdir(prefix: str = "p2e1_fb_"):
    with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
        yield Path(os.path.realpath(str(tmp)))


# ---------------------------------------------------------------------------
# Fake Flutter plumbing (mirrors the P2d1 selftest pattern; patches the
# loaded preflight module's shutil/subprocess only).
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
    """Install a fake flutter executable + patch the preflight module's
    ``shutil``/``subprocess`` references so the binding's preflight call
    succeeds without a host Flutter installation. Returns the resolved
    fake flutter path."""
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
def _restore(preflight_module):
    saved_shutil = preflight_module.shutil
    saved_subprocess = preflight_module.subprocess
    try:
        yield
    finally:
        preflight_module.shutil = saved_shutil
        preflight_module.subprocess = saved_subprocess


# ---------------------------------------------------------------------------
# Canonical fixture builders.
# ---------------------------------------------------------------------------


def _write_json(path: Path, payload: Any) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.write_bytes(data)
    return data


def _touch(path: Path, body: bytes = b"// fixture\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


def _build_minimal_flutter_project(proj: Path, *, name: str = "my_app") -> None:
    """Create the structure the project preflight requires."""
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
def _frozen_canonical_flutter_project(batch_id: str = "p2e1-fb-batch-1"):
    """Build a canonical Flutter project + frozen selection manifest and
    yield ``(project_root, run_root, manifest_path)`` where ``run_root``
    is the manifest's own ``<project>/.iff/icp_runs/<batch>`` internal
    run root.

    The yielded ``run_root`` is used both as the ``run_root`` for
    ``fixture_codegen`` requests (so the request's run root equals the
    frozen manifest run root exactly) and as a valid ``spec_root`` for
    P2d2c actions (it is a strict no-symlink descendant of the Flutter
    ``state_root`` ``<project>/.iff``).

    The Flutter preflight is NOT stubbed here; tests that drive the
    binding through ``prepare_binding`` must wrap their call in
    ``_with_fake_preflight(binding_module)``."""
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
# Representative operation request builders.
# ---------------------------------------------------------------------------


def _fixture_request(proj: Path, run_root: Path) -> dict[str, Any]:
    """A request for ``flutter.fixture_codegen.v1`` whose ``run_root`` is
    the frozen manifest's own internal run root (``run_root`` is the
    manifest run root yielded by ``_frozen_canonical_flutter_project``).
    The slot and projection inputs are placed inside that run root.
    P2.5b: fixture_codegen now also requires a ``projections`` map
    whose state-id set equals ``slots``."""
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
    """A request for ``flutter.fan_in.v1`` action=done_gate (P2d2c).
    ``spec_root`` is the manifest run root, which is a strict no-symlink
    descendant of the Flutter ``state_root`` ``<project>/.iff``."""
    return {
        "project_root": str(proj),
        "spec_root": str(spec_root),
        "action": "done_gate",
    }


# ---------------------------------------------------------------------------
# 1. Module surface.
# ---------------------------------------------------------------------------


def test_module_loads() -> None:
    module = _load("p2e1_fb_loads")
    assert module.KIND_BINDING == KIND_BINDING
    assert module.KIND_VERIFY == KIND_VERIFY
    assert module.SCHEMA_VERSION == SCHEMA_VERSION
    assert module.PLATFORM_ID == "flutter"
    assert module.PROFILE_ID == "flutter-standard"


def test_module_exposes_typed_exception() -> None:
    module = _load("p2e1_fb_exc")
    assert hasattr(module, "FlutterExecutionBindingError")
    assert issubclass(module.FlutterExecutionBindingError, Exception)


def test_module_has_no_cli_main() -> None:
    module = _load("p2e1_fb_nocli")
    assert not hasattr(module, "main")
    source = BINDING_PATH.read_text()
    assert '__name__ == "__main__"' not in source


def test_public_api_exposes_only_two_funcs_and_exception() -> None:
    module = _load("p2e1_fb_pubapi")
    assert callable(module.prepare_binding)
    assert callable(module.verify_binding)
    allowed_funcs = {"prepare_binding", "verify_binding"}
    public_funcs = [
        n
        for n in dir(module)
        if not n.startswith("_")
        and inspect.isfunction(getattr(module, n))
        and getattr(module, n).__module__ == module.__name__
    ]
    extra = sorted(set(public_funcs) - allowed_funcs)
    assert extra == [], f"unexpected public functions: {extra}"
    allowed_classes = {"FlutterExecutionBindingError"}
    public_classes = [
        n
        for n in dir(module)
        if not n.startswith("_")
        and inspect.isclass(getattr(module, n))
        and getattr(module, n).__module__ == module.__name__
    ]
    extra_c = sorted(set(public_classes) - allowed_classes)
    assert extra_c == [], f"unexpected public classes: {extra_c}"


def test_module_does_not_import_subprocess() -> None:
    source = BINDING_PATH.read_text()
    assert "import subprocess" not in source
    assert "subprocess.run" not in source
    assert "os.system" not in source
    assert "os.popen" not in source


# ---------------------------------------------------------------------------
# 2. Real binding build / verify round-trip for required ops.
# ---------------------------------------------------------------------------


def test_prepare_binding_fixture_codegen_succeeds() -> None:
    module = _load("p2e1_fb_prep_fixture")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            request = _fixture_request(proj, spec)
            binding = module.prepare_binding(mp, "flutter.fixture_codegen.v1", request)
        # Top-level shape.
        expected_keys = {
            "kind", "schema_version", "platform_id", "profile_id",
            "activation_state", "executable", "operation_id", "port_id",
            "capability_state", "selection_manifest_path",
            "selection_manifest_sha256", "selection_verification",
            "request", "request_digest", "plan", "plan_digest",
            "preflight", "preflight_digest", "descriptor_digest",
            "operations_module_sha256", "capsule_manifest_sha256",
        }
        assert set(binding.keys()) == expected_keys, set(binding.keys()) ^ expected_keys
        # Literals.
        assert binding["kind"] == KIND_BINDING
        assert binding["schema_version"] == SCHEMA_VERSION
        assert binding["platform_id"] == "flutter"
        assert binding["profile_id"] == "flutter-standard"
        assert binding["activation_state"] == "inactive"
        assert binding["executable"] is False
        assert binding["operation_id"] == "flutter.fixture_codegen.v1"
        assert binding["port_id"] == "fixture_codegen"
        assert binding["capability_state"] == "required"
        assert binding["selection_manifest_path"] == str(mp)
        # Selection manifest sha matches file bytes.
        expected_ms = hashlib.sha256(mp.read_bytes()).hexdigest()
        assert binding["selection_manifest_sha256"] == expected_ms
        # request_digest equals the plan's request_digest.
        assert binding["request_digest"] == binding["plan"]["request_digest"]
        # plan_digest is a sha256 hex.
        assert _is_sha256_hex(binding["plan_digest"])
        # preflight_digest is a sha256 hex over canonical preflight bytes.
        assert _is_sha256_hex(binding["preflight_digest"])
        expected_pd = hashlib.sha256(_canonical_json(binding["preflight"])).hexdigest()
        assert binding["preflight_digest"] == expected_pd
        # operations_module_sha256 over flutter_operations_v1.py bytes.
        expected_om = hashlib.sha256(OPERATIONS_PATH.read_bytes()).hexdigest()
        assert binding["operations_module_sha256"] == expected_om
        # capsule_manifest_sha256 over iff-v1-vendor.json bytes.
        expected_cm = hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest()
        assert binding["capsule_manifest_sha256"] == expected_cm
        # descriptor_digest is a sha256 hex (matches current descriptor verify).
        assert _is_sha256_hex(binding["descriptor_digest"])


def test_prepare_binding_p2d2c_fan_in_done_gate_succeeds() -> None:
    module = _load("p2e1_fb_prep_fanin")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            request = _fan_in_done_gate_request(proj, spec)
            binding = module.prepare_binding(mp, "flutter.fan_in.v1", request)
    assert binding["operation_id"] == "flutter.fan_in.v1"
    assert binding["port_id"] == "fan_in"
    assert binding["capability_state"] == "required"
    assert binding["executable"] is False


def test_prepare_binding_is_deterministic() -> None:
    module = _load("p2e1_fb_det")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            r1 = module.prepare_binding(mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec))
            r2 = module.prepare_binding(mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec))
    assert r1 == r2


def test_verify_binding_accepts_fresh_binding_fixture() -> None:
    module = _load("p2e1_fb_verify_fixture")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            binding = module.prepare_binding(mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec))
            report = module.verify_binding(binding)
    assert report["ok"] is True
    assert report["kind"] == KIND_VERIFY
    assert report["schema_version"] == SCHEMA_VERSION
    expected_keys = {
        "ok", "kind", "schema_version", "operation_id", "port_id",
        "binding_digest", "plan_digest", "selection_manifest_sha256",
    }
    assert set(report.keys()) == expected_keys, set(report.keys()) ^ expected_keys
    assert report["operation_id"] == "flutter.fixture_codegen.v1"
    assert report["port_id"] == "fixture_codegen"
    assert _is_sha256_hex(report["binding_digest"])
    assert _is_sha256_hex(report["plan_digest"])
    assert _is_sha256_hex(report["selection_manifest_sha256"])
    # binding_digest matches canonical bytes of the binding.
    expected_bd = hashlib.sha256(_canonical_json(binding)).hexdigest()
    assert report["binding_digest"] == expected_bd


def test_verify_binding_accepts_fresh_binding_fan_in() -> None:
    module = _load("p2e1_fb_verify_fanin")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            binding = module.prepare_binding(mp, "flutter.fan_in.v1", _fan_in_done_gate_request(proj, spec))
            report = module.verify_binding(binding)
    assert report["ok"] is True
    assert report["operation_id"] == "flutter.fan_in.v1"


# ---------------------------------------------------------------------------
# 3. Hard call order: selection verification first.
# ---------------------------------------------------------------------------


def test_selection_verification_runs_before_capsule_descriptor_preflight_build() -> None:
    """Force the selection verifier to fail; the binding must fail without
    invoking capsule/descriptor/preflight/build. Order is observed by
    counters patched onto each downstream API."""
    module = _load("p2e1_fb_order")
    counters = {"capsule": 0, "descriptor": 0, "preflight": 0, "build": 0}

    def _boom_verify(_path):
        raise module.FlutterExecutionBindingError("selection verifier injected failure")

    # Force-load the selection verifier module so we can patch its verify.
    sel_verify = module._load_selection_verify_module()
    saved_verify = sel_verify.verify
    sel_verify.verify = _boom_verify

    # Patch the binding's downstream cached modules so any call increments.
    desc_mod = module._load_descriptor_module()
    saved_desc = desc_mod.verify_descriptor

    def _count_desc():
        counters["descriptor"] += 1
        return saved_desc()

    desc_mod.verify_descriptor = _count_desc

    op_mod = module._load_operations_module()
    saved_build = op_mod.build

    def _count_build(oid, req):
        counters["build"] += 1
        return saved_build(oid, req)

    op_mod.build = _count_build
    try:
        with _frozen_canonical_flutter_project() as (proj, spec, mp):
            with _with_fake_preflight(module) as pfm:
                saved_preflight = pfm.preflight

                def _count_preflight(_root):
                    counters["preflight"] += 1
                    return saved_preflight(_root)

                pfm.preflight = _count_preflight
                try:
                    module.prepare_binding(
                        mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec)
                    )
                except module.FlutterExecutionBindingError as exc:
                    assert "selection verifier injected failure" in str(exc)
                else:
                    raise AssertionError("prepare did not fail on selection verifier failure")
    finally:
        sel_verify.verify = saved_verify
        desc_mod.verify_descriptor = saved_desc
        op_mod.build = saved_build
    assert counters == {"capsule": 0, "descriptor": 0, "preflight": 0, "build": 0}, counters


# ---------------------------------------------------------------------------
# 4. Exact mapping for all eight operation IDs and capability states.
# ---------------------------------------------------------------------------


def test_mapping_covers_all_eight_operation_ids() -> None:
    module = _load("p2e1_fb_map_all")
    # Build a binding for each operation that has a simple request shape.
    # For visibility, only fixture_codegen and fan_in done_gate are
    # exercised end-to-end here; the mapping for the other six is
    # asserted via the module's internal port map by direct prepare on
    # the simpler ops.
    # Use a project that satisfies every op's minimal needs by setting up
    # multiple spec artifacts. To keep this test focused, we directly
    # probe the module's private map.
    private_map = module._OPERATION_PORT_MAP
    assert set(private_map.keys()) == set(OPERATION_IDS)
    for op_id in OPERATION_IDS:
        assert private_map[op_id] == PORT_FOR_OPERATION[op_id]
    cap_map = module._OPERATION_CAPABILITY_MAP
    for op_id in OPERATION_IDS:
        assert cap_map[op_id] == CAPABILITY_FOR_OPERATION[op_id]


def test_prepare_rejects_project_preflight_operation_id() -> None:
    """``project_preflight`` is NOT one of the eight plan IDs and must
    be rejected even though it appears in the descriptor."""
    module = _load("p2e1_fb_reject_preflight_id")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            try:
                module.prepare_binding(mp, "project_preflight", {"project_root": str(proj)})
            except module.FlutterExecutionBindingError:
                pass
            else:
                raise AssertionError("project_preflight accepted as operation_id")


# ---------------------------------------------------------------------------
# 5. Project-root mismatch / non-Flutter / profile mismatch.
# ---------------------------------------------------------------------------


def test_prepare_rejects_project_root_mismatch() -> None:
    module = _load("p2e1_fb_proj_mismatch")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _canonical_tempdir() as other:
            other_proj = other / "other"
            other_proj.mkdir()
            _build_minimal_flutter_project(other_proj)
            with _with_fake_preflight(module):
                req = _fixture_request(proj, spec)
                req["project_root"] = str(other_proj)
                try:
                    module.prepare_binding(mp, "flutter.fixture_codegen.v1", req)
                except module.FlutterExecutionBindingError:
                    pass
                else:
                    raise AssertionError("project_root mismatch accepted")


def test_prepare_rejects_non_flutter_platform_manifest() -> None:
    """A frozen manifest whose platform is not ``flutter`` must be
    rejected at the platform check (the selection verifier still
    succeeds because it is platform-agnostic)."""
    module = _load("p2e1_fb_nonflutter")
    freeze = _load_freeze()
    common = _load_common()
    with _canonical_tempdir() as tmp:
        proj = tmp / "vproj"
        proj.mkdir()
        # Build a Vue manifest (state_root is .icp).
        resolved = {
            "task_source": "csv",
            "task_ref": "tasks.csv",
            "design_source": "lanhu-figma",
            "platform": "vue",
            "profile": "vue-vite",
            "project_root": str(proj),
        }
        ack = freeze.freeze_selection_manifest(
            resolved_config=resolved,
            candidates=_good_cands(),
            batch_id="vue-1",
            registries=common.load_registries(),
        )
        with _with_fake_preflight(module):
            try:
                module.prepare_binding(
                    ack["manifest_path"], "flutter.fixture_codegen.v1",
                    {"project_root": str(proj)},
                )
            except module.FlutterExecutionBindingError:
                pass
            else:
                raise AssertionError("non-flutter manifest accepted")


def test_prepare_rejects_unknown_operation_id() -> None:
    module = _load("p2e1_fb_unknown_op")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            try:
                module.prepare_binding(mp, "flutter.bogus.v1", {"project_root": str(proj)})
            except module.FlutterExecutionBindingError:
                pass
            else:
                raise AssertionError("unknown operation_id accepted")


# ---------------------------------------------------------------------------
# 6. Capability / descriptor drift / inactive requirement drift.
# ---------------------------------------------------------------------------


def test_prepare_rejects_descriptor_active_state_drift() -> None:
    """If the current descriptor returns ``activation_state != inactive``
    the binding must fail."""
    module = _load("p2e1_fb_desc_active")
    desc_mod = module._load_descriptor_module()
    saved = desc_mod.verify_descriptor

    def _drift():
        report = saved()
        report = copy.deepcopy(report)
        report["activation_state"] = "active"
        return report

    desc_mod.verify_descriptor = _drift
    try:
        with _frozen_canonical_flutter_project() as (proj, spec, mp):
            with _with_fake_preflight(module):
                try:
                    module.prepare_binding(
                        mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec)
                    )
                except module.FlutterExecutionBindingError:
                    pass
                else:
                    raise AssertionError("active descriptor accepted")
    finally:
        desc_mod.verify_descriptor = saved


def test_prepare_rejects_descriptor_executable_true() -> None:
    module = _load("p2e1_fb_desc_exec")
    desc_mod = module._load_descriptor_module()
    saved = desc_mod.verify_descriptor

    def _drift():
        report = saved()
        report = copy.deepcopy(report)
        report["executable"] = True
        return report

    desc_mod.verify_descriptor = _drift
    try:
        with _frozen_canonical_flutter_project() as (proj, spec, mp):
            with _with_fake_preflight(module):
                try:
                    module.prepare_binding(
                        mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec)
                    )
                except module.FlutterExecutionBindingError:
                    pass
                else:
                    raise AssertionError("descriptor executable=true accepted")
    finally:
        desc_mod.verify_descriptor = saved


# ---------------------------------------------------------------------------
# 7. Request mutation after prepare does not mutate binding.
# ---------------------------------------------------------------------------


def test_request_mutation_after_prepare_does_not_mutate_binding() -> None:
    module = _load("p2e1_fb_req_immutable")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            request = _fixture_request(proj, spec)
            binding = module.prepare_binding(mp, "flutter.fixture_codegen.v1", request)
            snapshot_req = copy.deepcopy(binding["request"])
            snapshot_plan = copy.deepcopy(binding["plan"])
            snapshot_sel = copy.deepcopy(binding["selection_verification"])
            snapshot_pref = copy.deepcopy(binding["preflight"])
            # Mutate the caller's request after prepare. The binding
            # holds a detached copy, so the embedded request/plan must
            # be unaffected.
            request["feature_id"] = "tampered"
            request["out"] = "lib/other.dart"
            request["slots"]["state_a"] = "nonexistent.json"
    # The binding's embedded copies must equal the pre-mutation snapshots.
    assert binding["request"] == snapshot_req
    assert binding["plan"] == snapshot_plan
    assert binding["selection_verification"] == snapshot_sel
    assert binding["preflight"] == snapshot_pref


# ---------------------------------------------------------------------------
# 8. Tamper every top-level literal/digest/report/request/plan/manifest path.
# ---------------------------------------------------------------------------


def _tamper_field(binding: dict, field: str, value) -> dict:
    new = copy.deepcopy(binding)
    new[field] = value
    return new


def test_verify_rejects_tamper_kind() -> None:
    module = _load("p2e1_fb_tamper_kind")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            b = module.prepare_binding(mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec))
            try:
                module.verify_binding(_tamper_field(b, "kind", "other"))
            except module.FlutterExecutionBindingError:
                pass
            else:
                raise AssertionError("kind tamper accepted")


def test_verify_rejects_tamper_schema_version() -> None:
    module = _load("p2e1_fb_tamper_sv")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            b = module.prepare_binding(mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec))
            try:
                module.verify_binding(_tamper_field(b, "schema_version", 2))
            except module.FlutterExecutionBindingError:
                pass
            else:
                raise AssertionError("schema_version tamper accepted")


def test_verify_rejects_tamper_executable_true() -> None:
    module = _load("p2e1_fb_tamper_exec")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            b = module.prepare_binding(mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec))
            try:
                module.verify_binding(_tamper_field(b, "executable", True))
            except module.FlutterExecutionBindingError:
                pass
            else:
                raise AssertionError("executable=true tamper accepted")


def test_verify_rejects_tamper_activation_state() -> None:
    module = _load("p2e1_fb_tamper_act")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            b = module.prepare_binding(mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec))
            try:
                module.verify_binding(_tamper_field(b, "activation_state", "active"))
            except module.FlutterExecutionBindingError:
                pass
            else:
                raise AssertionError("activation_state tamper accepted")


def test_verify_rejects_tamper_operation_id() -> None:
    module = _load("p2e1_fb_tamper_oid")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            b = module.prepare_binding(mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec))
            try:
                module.verify_binding(_tamper_field(b, "operation_id", "flutter.visible_codegen.v1"))
            except module.FlutterExecutionBindingError:
                pass
            else:
                raise AssertionError("operation_id tamper accepted")


def test_verify_rejects_tamper_port_id() -> None:
    module = _load("p2e1_fb_tamper_port")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            b = module.prepare_binding(mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec))
            try:
                module.verify_binding(_tamper_field(b, "port_id", "visible_codegen"))
            except module.FlutterExecutionBindingError:
                pass
            else:
                raise AssertionError("port_id tamper accepted")


def test_verify_rejects_tamper_capability_state() -> None:
    module = _load("p2e1_fb_tamper_cap")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            b = module.prepare_binding(mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec))
            try:
                module.verify_binding(_tamper_field(b, "capability_state", "unsupported"))
            except module.FlutterExecutionBindingError:
                pass
            else:
                raise AssertionError("capability_state tamper accepted")


def test_verify_rejects_tamper_manifest_path() -> None:
    module = _load("p2e1_fb_tamper_mp")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            b = module.prepare_binding(mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec))
            # Move the manifest to a sibling path; candidate says different path.
            other = mp.parent / "moved.json"
            other.write_bytes(mp.read_bytes())
            try:
                module.verify_binding(_tamper_field(b, "selection_manifest_path", str(other)))
            except module.FlutterExecutionBindingError:
                pass
            else:
                raise AssertionError("selection_manifest_path tamper accepted")


def test_verify_rejects_tamper_manifest_sha() -> None:
    module = _load("p2e1_fb_tamper_ms")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            b = module.prepare_binding(mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec))
            try:
                module.verify_binding(_tamper_field(b, "selection_manifest_sha256", "0" * 64))
            except module.FlutterExecutionBindingError:
                pass
            else:
                raise AssertionError("selection_manifest_sha256 tamper accepted")


def test_verify_rejects_tamper_request_digest() -> None:
    module = _load("p2e1_fb_tamper_rd")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            b = module.prepare_binding(mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec))
            try:
                module.verify_binding(_tamper_field(b, "request_digest", "a" * 64))
            except module.FlutterExecutionBindingError:
                pass
            else:
                raise AssertionError("request_digest tamper accepted")


def test_verify_rejects_tamper_plan_digest() -> None:
    module = _load("p2e1_fb_tamper_pd")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            b = module.prepare_binding(mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec))
            try:
                module.verify_binding(_tamper_field(b, "plan_digest", "b" * 64))
            except module.FlutterExecutionBindingError:
                pass
            else:
                raise AssertionError("plan_digest tamper accepted")


def test_verify_rejects_tamper_preflight_digest() -> None:
    module = _load("p2e1_fb_tamper_pfd")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            b = module.prepare_binding(mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec))
            try:
                module.verify_binding(_tamper_field(b, "preflight_digest", "c" * 64))
            except module.FlutterExecutionBindingError:
                pass
            else:
                raise AssertionError("preflight_digest tamper accepted")


def test_verify_rejects_tamper_descriptor_digest() -> None:
    module = _load("p2e1_fb_tamper_dd")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            b = module.prepare_binding(mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec))
            try:
                module.verify_binding(_tamper_field(b, "descriptor_digest", "d" * 64))
            except module.FlutterExecutionBindingError:
                pass
            else:
                raise AssertionError("descriptor_digest tamper accepted")


def test_verify_rejects_tamper_operations_module_sha() -> None:
    module = _load("p2e1_fb_tamper_om")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            b = module.prepare_binding(mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec))
            try:
                module.verify_binding(_tamper_field(b, "operations_module_sha256", "e" * 64))
            except module.FlutterExecutionBindingError:
                pass
            else:
                raise AssertionError("operations_module_sha256 tamper accepted")


def test_verify_rejects_tamper_capsule_manifest_sha() -> None:
    module = _load("p2e1_fb_tamper_cm")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            b = module.prepare_binding(mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec))
            try:
                module.verify_binding(_tamper_field(b, "capsule_manifest_sha256", "f" * 64))
            except module.FlutterExecutionBindingError:
                pass
            else:
                raise AssertionError("capsule_manifest_sha256 tamper accepted")


def test_verify_rejects_tamper_request_payload() -> None:
    module = _load("p2e1_fb_tamper_req")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            b = module.prepare_binding(mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec))
            tampered = copy.deepcopy(b)
            tampered["request"]["feature_id"] = "tampered_id"
            try:
                module.verify_binding(tampered)
            except module.FlutterExecutionBindingError:
                pass
            else:
                raise AssertionError("request payload tamper accepted")


def test_verify_rejects_tamper_plan_cwd() -> None:
    module = _load("p2e1_fb_tamper_pcwd")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            b = module.prepare_binding(mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec))
            tampered = copy.deepcopy(b)
            tampered["plan"]["steps"][0]["cwd"] = "/tmp/tampered"
            try:
                module.verify_binding(tampered)
            except module.FlutterExecutionBindingError:
                pass
            else:
                raise AssertionError("plan cwd tamper accepted")


def test_verify_rejects_tamper_plan_argv() -> None:
    module = _load("p2e1_fb_tamper_pargv")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            b = module.prepare_binding(mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec))
            tampered = copy.deepcopy(b)
            tampered["plan"]["steps"][0]["argv"].append("--INJECTED")
            try:
                module.verify_binding(tampered)
            except module.FlutterExecutionBindingError:
                pass
            else:
                raise AssertionError("plan argv tamper accepted")


def test_verify_rejects_coordinated_request_plus_plan_rewrite_with_different_project_root() -> None:
    """A coordinated rewrite of request + plan that points at a different
    project_root than the frozen manifest must fail because the rebuilt
    plan's project_root no longer matches the frozen one."""
    module = _load("p2e1_fb_coordinated")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _canonical_tempdir() as other_tmp:
            other_proj = other_tmp / "other"
            other_proj.mkdir()
            _build_minimal_flutter_project(other_proj)
            other_spec = other_tmp / "spec"
            other_spec.mkdir()
            with _with_fake_preflight(module):
                # Build a fresh binding for the OTHER project (same
                # operation, different project_root/spec_root).
                # Selection manifest used here is still the original
                # frozen manifest for ``proj``.
                req_other = _fixture_request(other_proj, other_spec)
                plan_other = module._load_operations_module().build(
                    "flutter.fixture_codegen.v1", req_other
                )
                # Replace the candidate binding's request/plan with the
                # other-project ones, but keep manifest_path/sha pointing
                # at the original frozen manifest.
                b = module.prepare_binding(
                    mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec)
                )
                tampered = copy.deepcopy(b)
                tampered["request"] = copy.deepcopy(req_other)
                tampered["plan"] = copy.deepcopy(plan_other)
                tampered["request_digest"] = plan_other["request_digest"]
                # plan_digest for the new plan from verify_plan.
                vp = module._load_operations_module().verify_plan(plan_other)
                tampered["plan_digest"] = vp["plan_digest"]
                try:
                    module.verify_binding(tampered)
                except module.FlutterExecutionBindingError:
                    pass
                else:
                    raise AssertionError("coordinated request+plan rewrite accepted")


# ---------------------------------------------------------------------------
# 9. Forbidden key / type confusion / extra field / non-dict.
# ---------------------------------------------------------------------------


def test_verify_rejects_non_dict() -> None:
    module = _load("p2e1_fb_nondict")
    for candidate in ([], "string", 42, None):
        try:
            module.verify_binding(candidate)
        except module.FlutterExecutionBindingError:
            pass
        else:
            raise AssertionError(f"non-dict candidate accepted: {candidate!r}")


def test_verify_rejects_missing_key() -> None:
    module = _load("p2e1_fb_missing")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            b = module.prepare_binding(mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec))
            for key in list(b.keys()):
                tampered = copy.deepcopy(b)
                del tampered[key]
                try:
                    module.verify_binding(tampered)
                except module.FlutterExecutionBindingError:
                    pass
                else:
                    raise AssertionError(f"missing key {key!r} accepted")


def test_verify_rejects_extra_key() -> None:
    module = _load("p2e1_fb_extra")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            b = module.prepare_binding(mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec))
            tampered = copy.deepcopy(b)
            tampered["extra_top_level"] = "boom"
            try:
                module.verify_binding(tampered)
            except module.FlutterExecutionBindingError:
                pass
            else:
                raise AssertionError("extra top-level key accepted")


def test_verify_rejects_executable_int_zero_confusion() -> None:
    module = _load("p2e1_fb_boolint")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            b = module.prepare_binding(mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec))
            tampered = copy.deepcopy(b)
            tampered["executable"] = 0
            try:
                module.verify_binding(tampered)
            except module.FlutterExecutionBindingError:
                pass
            else:
                raise AssertionError("executable=0 (int) accepted as false")


def test_verify_rejects_malformed_digest() -> None:
    module = _load("p2e1_fb_maldig")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            b = module.prepare_binding(mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec))
            for field in ("selection_manifest_sha256", "request_digest", "plan_digest",
                          "preflight_digest", "descriptor_digest",
                          "operations_module_sha256", "capsule_manifest_sha256"):
                tampered = copy.deepcopy(b)
                tampered[field] = "XYZ"  # not a sha256 hex
                try:
                    module.verify_binding(tampered)
                except module.FlutterExecutionBindingError:
                    pass
                else:
                    raise AssertionError(f"malformed digest {field!r} accepted")


# ---------------------------------------------------------------------------
# 10. Preflight / capsule / descriptor / plan failure redaction.
# ---------------------------------------------------------------------------


def test_prepare_redacts_preflight_failure() -> None:
    module = _load("p2e1_fb_preflight_fail")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module) as pfm:
            def _boom(_root):
                raise RuntimeError("SECRET_PREFLIGHT_DETAIL")
            pfm.preflight = _boom
            try:
                module.prepare_binding(
                    mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec)
                )
            except module.FlutterExecutionBindingError as exc:
                msg = str(exc)
                assert "SECRET_PREFLIGHT_DETAIL" not in msg
                assert "RuntimeError" in msg or "preflight" in msg.lower()
            else:
                raise AssertionError("preflight generic failure not raised")


def test_prepare_redacts_capsule_failure() -> None:
    module = _load("p2e1_fb_capsule_fail")
    desc_mod = module._load_descriptor_module()
    saved = desc_mod.verify_descriptor

    def _boom():
        raise RuntimeError("SECRET_CAPSULE_DETAIL")
    desc_mod.verify_descriptor = _boom
    try:
        with _frozen_canonical_flutter_project() as (proj, spec, mp):
            with _with_fake_preflight(module):
                try:
                    module.prepare_binding(
                        mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec)
                    )
                except module.FlutterExecutionBindingError as exc:
                    msg = str(exc)
                    assert "SECRET_CAPSULE_DETAIL" not in msg
                else:
                    raise AssertionError("capsule generic failure not raised")
    finally:
        desc_mod.verify_descriptor = saved


def test_prepare_redacts_plan_build_failure() -> None:
    module = _load("p2e1_fb_plan_fail")
    op_mod = module._load_operations_module()
    saved = op_mod.build

    def _boom(_oid, _req):
        raise RuntimeError("SECRET_PLAN_DETAIL")
    op_mod.build = _boom
    try:
        with _frozen_canonical_flutter_project() as (proj, spec, mp):
            with _with_fake_preflight(module):
                try:
                    module.prepare_binding(
                        mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec)
                    )
                except module.FlutterExecutionBindingError as exc:
                    msg = str(exc)
                    assert "SECRET_PLAN_DETAIL" not in msg
                else:
                    raise AssertionError("plan build generic failure not raised")
    finally:
        op_mod.build = saved


# ---------------------------------------------------------------------------
# 11. No operation plan is executed; executable always false; no writes.
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


def test_prepare_does_not_execute_operation_plan() -> None:
    """The binding must never invoke subprocess.run / shell for the
    operation plan; only the fixed preflight's ``flutter --version``
    subprocess is allowed (and is stubbed here)."""
    module = _load("p2e1_fb_noexec")
    # Patch the binding's loaded operations module to ensure build /
    # verify_plan never invoke a subprocess. flutter_operations_v1
    # already does not import subprocess; assert the invariant here.
    op_mod = module._load_operations_module()
    assert not hasattr(op_mod, "subprocess")
    op_src = OPERATIONS_PATH.read_text()
    assert "import subprocess" not in op_src
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            binding = module.prepare_binding(
                mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec)
            )
            # binding carries the plan but no execution surface.
            assert binding["executable"] is False
            assert binding["activation_state"] == "inactive"


def test_prepare_does_not_mutate_project_or_spec() -> None:
    module = _load("p2e1_fb_nowrite")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            # Build the request first (this writes the slot input into
            # the run_root); then snapshot before prepare_binding so the
            # no-write check measures only prepare_binding's effect.
            request = _fixture_request(proj, spec)
            before_proj = _snapshot(proj)
            before_spec = _snapshot(spec)
            module.prepare_binding(
                mp, "flutter.fixture_codegen.v1", request
            )
            after_proj = _snapshot(proj)
            after_spec = _snapshot(spec)
    assert set(before_proj.keys()) == set(after_proj.keys())
    for p, data in before_proj.items():
        assert after_proj[p] == data, f"project mutated: {p}"
    assert set(before_spec.keys()) == set(after_spec.keys())
    for p, data in before_spec.items():
        assert after_spec[p] == data, f"spec mutated: {p}"


def test_prepare_does_not_mutate_descriptor_or_capsule_or_registry() -> None:
    module = _load("p2e1_fb_nowrite_prod")
    before_reg = REGISTRY_PATH.read_bytes()
    before_desc = DESCRIPTOR_PATH.read_bytes()
    before_capsule = MANIFEST_PATH.read_bytes()
    before_skill = SKILL_MD_PATH.read_bytes()
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            module.prepare_binding(
                mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec)
            )
    assert REGISTRY_PATH.read_bytes() == before_reg
    assert DESCRIPTOR_PATH.read_bytes() == before_desc
    assert MANIFEST_PATH.read_bytes() == before_capsule
    assert SKILL_MD_PATH.read_bytes() == before_skill


def test_executable_is_always_false_for_all_operations() -> None:
    """For each operation we exercise in this test (fixture_codegen and
    fan_in done_gate), the binding must report executable=False."""
    module = _load("p2e1_fb_execfalse")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(module):
            b1 = module.prepare_binding(
                mp, "flutter.fixture_codegen.v1", _fixture_request(proj, spec)
            )
            b2 = module.prepare_binding(
                mp, "flutter.fan_in.v1", _fan_in_done_gate_request(proj, spec)
            )
    assert b1["executable"] is False
    assert b2["executable"] is False
    assert b1["activation_state"] == "inactive"
    assert b2["activation_state"] == "inactive"


# ---------------------------------------------------------------------------
# 12. spec_root containment rule (state_root descendant or run_root).
# ---------------------------------------------------------------------------


def test_prepare_accepts_spec_root_under_state_root_iff_lanhu_layout() -> None:
    """The compatibility ``.iff/lanhu/specs/...`` layout is a strict
    descendant of the Flutter state_root (``<project>/.iff``) and must
    be accepted as ``spec_root``."""
    module = _load("p2e1_fb_spec_state")
    freeze = _load_freeze()
    common = _load_common()
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        proj.mkdir()
        _build_minimal_flutter_project(proj)
        # The state root for flutter is <project>/.iff (the run_root is
        # beneath <project>/.iff/icp_runs). A spec_root beneath .iff is
        # both the legacy layout and a descendant of state_root.
        spec = proj / ".iff" / "lanhu" / "specs" / "feature_x"
        spec.mkdir(parents=True)
        ack = freeze.freeze_selection_manifest(
            resolved_config=_resolved(proj),
            candidates=_good_cands(),
            batch_id="specstate-1",
            registries=common.load_registries(),
        )
        with _with_fake_preflight(module):
            request = _fan_in_done_gate_request(proj, spec)
            binding = module.prepare_binding(mp := ack["manifest_path"], "flutter.fan_in.v1", request)
    assert binding["operation_id"] == "flutter.fan_in.v1"


def test_prepare_rejects_unrelated_external_spec_root() -> None:
    """An unrelated external spec_root (not under the frozen state_root
    nor under the run_root) must be rejected."""
    module = _load("p2e1_fb_spec_external")
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _canonical_tempdir() as elsewhere:
            external_spec = elsewhere / "unrelated"
            external_spec.mkdir()
            with _with_fake_preflight(module):
                req = _fan_in_done_gate_request(proj, external_spec)
                try:
                    module.prepare_binding(mp, "flutter.fan_in.v1", req)
                except module.FlutterExecutionBindingError:
                    pass
                else:
                    raise AssertionError("external spec_root accepted")


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
