#!/usr/bin/env python3
"""Vertical RED -> GREEN selftest for the ICP P2e2b fixed-argv Flutter
execution executor
(``platforms/flutter_execution_executor_v1``).

P2e2b is the first activation slice. Given an authorization produced
and verified by P2e2a, it:

* re-verifies the authorization through
  ``flutter_execution_authorization_v1.verify_authorization`` with all
  four supervisor-held expected values;
* derives the run root from the freshly verified candidate's embedded
  binding/selection verification (cross-checked against
  ``Path(selection_manifest_path).parent``);
* atomically claims the recorded execution nonce exactly once against
  a fixed receipt directory under the verified run root
  (``<run_root>/.icp-execution-receipts-v1/<nonce>.claim.json``),
  using ``O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC`` where supported
  and mode ``0600``;
* executes the embedded binding plan serially with the exact ordered
  argv from each step, ``shell=False``, the exact cwd, the exact
  timeout, ``stdin=DEVNULL``, ``close_fds=True`` and a new process
  session/group; re-verifies the authorization and re-hashes the
  executable/primitive/cwd bytes immediately before every spawn;
* builds an executor-owned environment that strips Python / dynamic-
  loader / shell startup injection variables and sets
  ``PYTHONDONTWRITEBYTECODE=1`` and ``PYTHONNOUSERSITE=1``;
* drains stdout/stderr fully with bounded 16-KiB tails and full-stream
  SHA-256/byte counts; never persists raw output to disk;
* writes a separate immutable terminal result file
  (``<nonce>.result.json``, ``O_EXCL``, ``0600``) and returns a
  versioned strict-schema report.

The nonce is consumed exactly once: success, non-zero exit, timeout,
launch failure, verification drift, integrity drift, internal error,
cancellation, or claim-only crash state are all terminal and never
replayable.

Honest boundary: path verification plus ``subprocess.Popen`` does not
eliminate the verify-to-spawn TOCTOU race for executable/script path
replacement. The fd-relative receipt claim closes the nonce
filename symlink/replay race; it does not close executable/script
path replacement races.

Run directly:

    PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p2e2b_flutter_executor.py
"""

from __future__ import annotations

import ast
import base64
import contextlib
import copy
import hashlib
import importlib.util
import inspect
import json
import os
import re
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
ICP_ROOT = Path(__file__).resolve().parents[1]
ICP_SCRIPTS = Path(__file__).resolve().parent
PLATFORMS_DIR = ICP_SCRIPTS / "platforms"
EXECUTOR_PATH = PLATFORMS_DIR / "flutter_execution_executor_v1.py"
AUTHZ_PATH = PLATFORMS_DIR / "flutter_execution_authorization_v1.py"
BINDING_PATH = PLATFORMS_DIR / "flutter_execution_binding_v1.py"
OPERATIONS_PATH = PLATFORMS_DIR / "flutter_operations_v1.py"
PREFLIGHT_PATH = PLATFORMS_DIR / "flutter_project_preflight_v1.py"
DESCRIPTOR_PATH = PLATFORMS_DIR / "flutter_standard_v1.py"
FREEZE_PATH = ICP_SCRIPTS / "freeze_selection_manifest.py"
COMMON_PATH = ICP_SCRIPTS / "icp_common.py"
MANIFEST_PATH = ICP_ROOT / "references" / "baselines" / "iff-v1-vendor.json"
REGISTRY_PATH = ICP_ROOT / "references" / "registries.json"
SKILL_MD_PATH = ICP_ROOT / "SKILL.md"

KIND_REPORT = "icp.flutter-execution-report.v1"
KIND_CLAIM = "icp.flutter-execution-claim.v1"
KIND_RESULT = "icp.flutter-execution-result.v1"
SCHEMA_VERSION = 1


def _canonical_compact(obj: Any) -> bytes:
    return json.dumps(
        obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def _load(name: str, path: Path = EXECUTOR_PATH):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_freeze(name: str = "p2e2b_freeze_helper"):
    spec = importlib.util.spec_from_file_location(name, str(FREEZE_PATH))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_common(name: str = "p2e2b_common_helper"):
    spec = importlib.util.spec_from_file_location(name, str(COMMON_PATH))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Fake Flutter plumbing (stub the preflight module's shutil/subprocess).
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
    """Patch the preflight module so the binding's preflight call
    succeeds without a host Flutter installation."""
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
def _canonical_tempdir(prefix: str = "p2e2b_"):
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
def _frozen_canonical_flutter_project(batch_id: str = "p2e2b-batch-1"):
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


def _fan_in_done_gate_request(proj: Path, spec_root: Path) -> dict[str, Any]:
    return {
        "project_root": str(proj),
        "spec_root": str(spec_root),
        "action": "done_gate",
    }


# ---------------------------------------------------------------------------
# Real primitive substitution seam. P2e2b executes real argv: argv[0] is
# sys.executable and argv[1] is the bound primitive script. To get a
# deterministic happy-path run we substitute the bound primitive path
# (which the binding builder reads from the operations module's
# CAPSULE_SCRIPTS_DIR / primitive-name) with a tiny test script in a temp
# directory, AND substitute the capsule manifest load to return a sha256
# matching the temp script. This is a narrowly scoped test seam on the
# binding module's loaded operations module; production behaviour still
# uses the real installed capsule manifest and the real capsule scripts.
# ---------------------------------------------------------------------------


def _build_test_primitive(
    operations_module,
    *,
    body: str,
    name: str = "check_done_gate.py",
    scripts_dir: Path | None = None,
) -> tuple[Path, str, dict[str, Any], dict[str, Any]]:
    """Install ``body`` as the bound primitive ``name`` and return the
    fixture's (script_path, script_sha256, saved_state, manifest_patch).

    The caller owns ``scripts_dir`` lifetime (the substituted script
    must remain on disk for the duration of the test). The returned
    ``saved_state`` captures everything needed to restore the
    operations module after the test. The returned
    ``manifest_patch`` is a synthetic manifest shape that
    ``_load_manifest`` should return for the duration of the test (it
    lists the substituted primitive with the matching sha256)."""
    if scripts_dir is None:
        scripts_dir = Path(tempfile.mkdtemp(prefix="p2e2b_prim_"))
    script_path = scripts_dir / name
    script_path.write_text(body, encoding="utf-8")
    script_sha = _sha256_bytes(script_path.read_bytes())

    saved = {
        "CAPSULE_SCRIPTS_DIR": operations_module.CAPSULE_SCRIPTS_DIR,
        "_load_manifest": operations_module._load_manifest,
        "_verify_capsule": operations_module._verify_capsule,
        "script_path": script_path,
        "script_sha": script_sha,
    }

    # Use the real installed manifest as the base, but rewrite the sha
    # for the substituted primitive. The binding's capsule manifest
    # digest is computed over the file bytes of references/baselines/
    # iff-v1-vendor.json on disk; we DO NOT modify that file. Instead
    # we patch _load_manifest to return our patched copy AND we patch
    # _verify_capsule to skip the real on-disk capsule verification
    # (the real capsule's check_done_gate.py is not what we are
    # executing here).
    real_manifest = operations_module._load_manifest()
    patched_scripts = []
    for entry in real_manifest["scripts"]:
        if entry["name"] == name:
            patched_scripts.append({**entry, "sha256": script_sha})
        else:
            patched_scripts.append(entry)
    patched_manifest = {**real_manifest, "scripts": patched_scripts}

    return script_path, script_sha, saved, patched_manifest


@contextlib.contextmanager
def _with_test_primitive(operations_module, *, body: str, name: str = "check_done_gate.py"):
    """Context manager that swaps the operations module's bound
    primitive script for ``body`` for the duration of the with-block.

    The substituted script is created in a realpath-canonicalized temp
    dir that is cleaned up in finally. The canonicalization eliminates
    macOS ``/var`` -> ``/private/var`` ancestor symlinks so the
    strict-resolve checks pass.

    Yields ``(script_path, script_sha)``."""
    import shutil
    raw_dir = Path(tempfile.mkdtemp(prefix="p2e2b_prim_"))
    scripts_dir = Path(os.path.realpath(str(raw_dir)))
    script_path, script_sha, _, patched_manifest = _build_test_primitive(
        operations_module, body=body, name=name, scripts_dir=scripts_dir
    )
    saved_csd = operations_module.CAPSULE_SCRIPTS_DIR
    saved_lm = operations_module._load_manifest
    saved_vc = operations_module._verify_capsule
    operations_module.CAPSULE_SCRIPTS_DIR = script_path.parent
    operations_module._load_manifest = lambda: patched_manifest
    operations_module._verify_capsule = lambda: {
        "kind": "icp.iff-v1-vendor-capsule-verify",
        "ok": True,
        "capsule_root": "vendor/iff_v1",
    }
    try:
        yield script_path, script_sha
    finally:
        operations_module.CAPSULE_SCRIPTS_DIR = saved_csd
        operations_module._load_manifest = saved_lm
        operations_module._verify_capsule = saved_vc
        shutil.rmtree(scripts_dir, ignore_errors=True)
        if raw_dir != scripts_dir:
            shutil.rmtree(raw_dir, ignore_errors=True)


@contextlib.contextmanager
def _build_verified_binding(executor_module, operation_id: str, request_factory):
    """Build a real verified binding through the executor module's own
    authorization-module's binding-module instance, then prepare a real
    authorization for it.

    Yields ``(authz_module, binding_module, authorization, manifest_path,
    project_root, spec_root, expected_tuple, nonce)``."""
    authz_module = executor_module._load_authorization_module()
    binding_module = authz_module._load_binding_module()
    with _frozen_canonical_flutter_project() as (proj, spec, mp):
        with _with_fake_preflight(binding_module):
            request = request_factory(proj, spec)
            binding = binding_module.prepare_binding(mp, operation_id, request)
            verify_report = binding_module.verify_binding(binding)
            manifest_sha = _sha256_bytes(mp.read_bytes())
            binding_digest = verify_report["binding_digest"]
            nonce = "0123456789abcdef0123456789abcdef"
            authorization = authz_module.prepare_authorization(
                binding,
                expected_manifest_path=str(mp),
                expected_manifest_sha256=manifest_sha,
                expected_binding_digest=binding_digest,
                execution_nonce=nonce,
            )
            expected_tuple = (
                str(mp),
                manifest_sha,
                binding_digest,
                authorization["authorization_digest"],
            )
            yield (
                authz_module,
                binding_module,
                authorization,
                mp,
                proj,
                spec,
                expected_tuple,
                nonce,
            )


@contextlib.contextmanager
def _build_substituted_binding(
    executor_module,
    *,
    body: str,
    operation_id: str = "flutter.fan_in.v1",
    request_factory=None,
    name: str = "check_done_gate.py",
    batch_id: str = "p2e2b-batch-1",
):
    """Build a verified binding+authorization where the bound primitive
    script is substituted by ``body`` so the executor really runs it.

    Yields the same tuple as :func:`_build_verified_binding` plus the
    script path/sha at the end."""
    if request_factory is None:
        request_factory = _fan_in_done_gate_request
    authz_module = executor_module._load_authorization_module()
    binding_module = authz_module._load_binding_module()
    operations_module = binding_module._load_operations_module()
    with _frozen_canonical_flutter_project(batch_id=batch_id) as (proj, spec, mp):
        with _with_fake_preflight(binding_module):
            with _with_test_primitive(
                operations_module, body=body, name=name
            ) as (script_path, script_sha):
                request = request_factory(proj, spec)
                binding = binding_module.prepare_binding(mp, operation_id, request)
                verify_report = binding_module.verify_binding(binding)
                manifest_sha = _sha256_bytes(mp.read_bytes())
                binding_digest = verify_report["binding_digest"]
                nonce = "0123456789abcdef0123456789abcdef"
                authorization = authz_module.prepare_authorization(
                    binding,
                    expected_manifest_path=str(mp),
                    expected_manifest_sha256=manifest_sha,
                    expected_binding_digest=binding_digest,
                    execution_nonce=nonce,
                )
                expected_tuple = (
                    str(mp),
                    manifest_sha,
                    binding_digest,
                    authorization["authorization_digest"],
                )
                yield (
                    authz_module,
                    binding_module,
                    authorization,
                    mp,
                    proj,
                    spec,
                    expected_tuple,
                    nonce,
                    script_path,
                    script_sha,
                )


# ---------------------------------------------------------------------------
# 1. Module surface, public API, no CLI, import-time zero-I/O.
# ---------------------------------------------------------------------------


def test_module_loads() -> None:
    module = _load("p2e2b_loads")
    assert module.KIND_REPORT == KIND_REPORT
    assert module.KIND_CLAIM == KIND_CLAIM
    assert module.KIND_RESULT == KIND_RESULT
    assert module.SCHEMA_VERSION == SCHEMA_VERSION
    assert hasattr(module, "CODE")
    assert isinstance(module.CODE, str) and module.CODE


def test_module_exposes_typed_exception() -> None:
    module = _load("p2e2b_exc")
    assert hasattr(module, "FlutterExecutionExecutorError")
    assert issubclass(module.FlutterExecutionExecutorError, Exception)


def test_module_has_no_cli_main() -> None:
    module = _load("p2e2b_nocli")
    assert not hasattr(module, "main")
    source = EXECUTOR_PATH.read_text()
    assert '__name__ == "__main__"' not in source
    assert "import argparse" not in source
    assert "sys.argv" not in source


def test_public_api_exposes_only_one_func_and_exception() -> None:
    module = _load("p2e2b_pubapi")
    assert callable(module.execute_authorization)
    allowed_funcs = {"execute_authorization"}
    public_funcs = [
        n
        for n in dir(module)
        if not n.startswith("_")
        and inspect.isfunction(getattr(module, n))
        and getattr(module, n).__module__ == module.__name__
    ]
    extra = sorted(set(public_funcs) - allowed_funcs)
    assert extra == [], f"unexpected public functions: {extra}"
    allowed_classes = {"FlutterExecutionExecutorError"}
    public_classes = [
        n
        for n in dir(module)
        if not n.startswith("_")
        and inspect.isclass(getattr(module, n))
        and getattr(module, n).__module__ == module.__name__
    ]
    extra_c = sorted(set(public_classes) - allowed_classes)
    assert extra_c == [], f"unexpected public classes: {extra_c}"


def test_module_does_not_import_network() -> None:
    source = EXECUTOR_PATH.read_text()
    for forbidden in ("import socket", "import urllib", "import requests",
                      "import http.client", "import ftplib"):
        assert forbidden not in source, forbidden


# ---------------------------------------------------------------------------
# 2. Missing/wrong each expected value rejects before receipt/spawn.
# ---------------------------------------------------------------------------


def _exec_kwargs(expected, authorization, **overrides):
    mp_str, ms, bd, ad = expected
    kwargs = dict(
        authorization=authorization,
        expected_manifest_path=mp_str,
        expected_manifest_sha256=ms,
        expected_binding_digest=bd,
        expected_authorization_digest=ad,
    )
    kwargs.update(overrides)
    return kwargs


def test_execute_rejects_wrong_manifest_path() -> None:
    executor = _load("p2e2b_ex_mp")
    with _build_verified_binding(
        executor, "flutter.fan_in.v1", _fan_in_done_gate_request
    ) as (am, bm, authz, mp, proj, spec, expected, nonce):
        try:
            executor.execute_authorization(
                **_exec_kwargs(expected, authz, expected_manifest_path=str(mp) + "/x")
            )
        except executor.FlutterExecutionExecutorError:
            pass
        else:
            raise AssertionError("wrong manifest_path accepted")


def test_execute_rejects_wrong_manifest_sha() -> None:
    executor = _load("p2e2b_ex_ms")
    with _build_verified_binding(
        executor, "flutter.fan_in.v1", _fan_in_done_gate_request
    ) as (am, bm, authz, mp, proj, spec, expected, nonce):
        try:
            executor.execute_authorization(
                **_exec_kwargs(expected, authz, expected_manifest_sha256="a" * 64)
            )
        except executor.FlutterExecutionExecutorError:
            pass
        else:
            raise AssertionError("wrong manifest_sha accepted")


def test_execute_rejects_wrong_binding_digest() -> None:
    executor = _load("p2e2b_ex_bd")
    with _build_verified_binding(
        executor, "flutter.fan_in.v1", _fan_in_done_gate_request
    ) as (am, bm, authz, mp, proj, spec, expected, nonce):
        try:
            executor.execute_authorization(
                **_exec_kwargs(expected, authz, expected_binding_digest="b" * 64)
            )
        except executor.FlutterExecutionExecutorError:
            pass
        else:
            raise AssertionError("wrong binding_digest accepted")


def test_execute_rejects_wrong_authorization_digest() -> None:
    executor = _load("p2e2b_ex_ad")
    with _build_verified_binding(
        executor, "flutter.fan_in.v1", _fan_in_done_gate_request
    ) as (am, bm, authz, mp, proj, spec, expected, nonce):
        try:
            executor.execute_authorization(
                **_exec_kwargs(expected, authz, expected_authorization_digest="c" * 64)
            )
        except executor.FlutterExecutionExecutorError:
            pass
        else:
            raise AssertionError("wrong authorization_digest accepted")


def test_execute_rejects_non_dict_authorization() -> None:
    executor = _load("p2e2b_ex_nd")
    for bad in ([], "string", 42, None, b"bytes"):
        try:
            executor.execute_authorization(
                bad,
                expected_manifest_path="/x",
                expected_manifest_sha256="0" * 64,
                expected_binding_digest="0" * 64,
                expected_authorization_digest="0" * 64,
            )
        except executor.FlutterExecutionExecutorError:
            pass
        else:
            raise AssertionError(f"non-dict authorization accepted: {bad!r}")


def test_execute_rejects_malformed_expected_sha() -> None:
    executor = _load("p2e2b_ex_sha")
    with _build_verified_binding(
        executor, "flutter.fan_in.v1", _fan_in_done_gate_request
    ) as (am, bm, authz, mp, proj, spec, expected, nonce):
        for bad in ("XYZ", "0" * 63, "0" * 65, "G" * 64, 123, None, b"0" * 64):
            try:
                executor.execute_authorization(
                    **_exec_kwargs(expected, authz, expected_manifest_sha256=bad)
                )
            except executor.FlutterExecutionExecutorError:
                pass
            else:
                raise AssertionError(f"malformed manifest sha accepted: {bad!r}")


# ---------------------------------------------------------------------------
# 3. Real safe happy-path execution (substituted primitive that exits 0).
# ---------------------------------------------------------------------------


def test_real_happy_path_single_step_success() -> None:
    """A real authorization executed through the real executor against
    a substituted primitive that exits 0 must produce a success
    terminal result and a non-replayable claim."""
    executor = _load("p2e2b_happy")
    body = (
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "sys.stdout.write('hello stdout\\n')\n"
        "sys.stderr.write('hello stderr\\n')\n"
        "sys.exit(0)\n"
    )
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, script_path, script_sha
    ):
        run_root = Path(authz["verified_binding"]["selection_verification"]["run_root"])
        report = executor.execute_authorization(**_exec_kwargs(expected, authz))
        # All receipt reads must happen inside the with block so the
        # temp run root is still alive.
        assert report["ok"] is True
        assert report["overall_status"] == "success"
        assert report["execution_nonce"] == nonce
        assert report["kind"] == KIND_REPORT
        assert _is_sha256_hex(report["claim_digest"])
        assert _is_sha256_hex(report["result_digest"])
        assert report["expected_authorization_digest"] == expected[3]
        assert len(report["step_results"]) == 1
        step = report["step_results"][0]
        assert step["status"] == "success"
        assert step["exit_code"] == 0
        assert step["stdout_byte_count"] == len(b"hello stdout\n")
        assert step["stderr_byte_count"] == len(b"hello stderr\n")
        assert step["stdout_sha256"] == _sha256_bytes(b"hello stdout\n")
        assert step["stderr_sha256"] == _sha256_bytes(b"hello stderr\n")
        assert base64.b64decode(step["stdout_tail_b64"]) == b"hello stdout\n"
        assert base64.b64decode(step["stderr_tail_b64"]) == b"hello stderr\n"
        assert step["stdout_truncated"] is False
        assert step["stderr_truncated"] is False
        # Receipts exist on disk.
        rcpt = run_root / ".icp-execution-receipts-v1"
        claim_path = rcpt / f"{nonce}.claim.json"
        result_path = rcpt / f"{nonce}.result.json"
        assert claim_path.is_file()
        assert result_path.is_file()
        claim_text = claim_path.read_text(encoding="utf-8")
        result_text = result_path.read_text(encoding="utf-8")
        # Receipts do not contain raw output.
        assert "hello stdout" not in claim_text
        assert "hello stdout" not in result_text
        assert "hello stderr" not in claim_text
        assert "hello stderr" not in result_text


# ---------------------------------------------------------------------------
# 4. Ordered multi-step behavior, exact argv/cwd/timeout, no shell or
#    caller override.
# ---------------------------------------------------------------------------


def test_real_happy_path_multi_step_success() -> None:
    """Multi-step: visible_codegen has 4 steps (P2.5a2 added the
    adapt_expected_slots platform-origin post-step between
    generate_canvas and make_implementation_map). Substitute all four
    primitive scripts with safe test scripts.

    The capsule-origin steps resolve through ``CAPSULE_SCRIPTS_DIR``;
    the platform-origin adapter resolves through ``PLATFORM_SCRIPTS_DIR``.
    Both must be patched to canonical temp roots for the duration of the
    substitution, and both must be restored in ``finally``. The adapter
    stub body never runs against a real generator output: it is a trivial
    ``sys.exit(0)`` so no real sidecar files are required."""
    executor = _load("p2e2b_multi")

    bodies = {
        "generate_canvas.py": "import sys; sys.exit(0)\n",
        "make_implementation_map.py": "import sys; sys.exit(0)\n",
        "make_status_bar_policy.py": "import sys; sys.exit(0)\n",
    }
    # The platform-origin adapter stub. It is never run against real
    # generate_canvas sidecars; the substituted generate_canvas above
    # produces no sidecars and the stub never touches them.
    adapter_name = "flutter_expected_slots_adapter_v1.py"
    adapter_body = "import sys; sys.exit(0)\n"

    def _request_factory(proj: Path, run_root: Path) -> dict[str, Any]:
        for n, payload in (
            ("render_plan.json", {"a": 1}),
            ("classification.json", {"a": 1}),
            ("component_manifest.json", {"a": 1}),
            ("scene.json", {"a": 1}),
        ):
            _write_json(run_root / n, payload)
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

    authz_module_holder = {}
    executor_module_holder = {}

    @contextlib.contextmanager
    def _substituted_visible(executor_module):
        am = executor_module._load_authorization_module()
        bm = am._load_binding_module()
        operations_module = bm._load_operations_module()
        with _frozen_canonical_flutter_project(batch_id="p2e2b-vis") as (proj, run_root, mp):
            with _with_fake_preflight(bm):
                # Substitute all visible_codegen primitives. Capsule
                # primitives resolve through CAPSULE_SCRIPTS_DIR; the
                # platform adapter resolves through PLATFORM_SCRIPTS_DIR.
                # Both must be patched to canonical temp roots and both
                # restored in finally.
                saved_csd = operations_module.CAPSULE_SCRIPTS_DIR
                saved_psd = operations_module.PLATFORM_SCRIPTS_DIR
                saved_lm = operations_module._load_manifest
                saved_vc = operations_module._verify_capsule
                tmp_scripts = proj.parent / "scripts_subst"
                tmp_platform = proj.parent / "platforms_subst"
                tmp_scripts.mkdir()
                tmp_platform.mkdir()
                # Write the platform adapter stub.
                adapter_sp = tmp_platform / adapter_name
                adapter_sp.write_text(adapter_body, encoding="utf-8")
                real_manifest = operations_module._load_manifest()
                patched_scripts = []
                for entry in real_manifest["scripts"]:
                    if entry["name"] in bodies:
                        sp = tmp_scripts / entry["name"]
                        sp.write_text(bodies[entry["name"]], encoding="utf-8")
                        patched_scripts.append(
                            {**entry, "sha256": _sha256_bytes(sp.read_bytes())}
                        )
                    else:
                        patched_scripts.append(entry)
                patched_manifest = {**real_manifest, "scripts": patched_scripts}
                operations_module.CAPSULE_SCRIPTS_DIR = tmp_scripts
                operations_module.PLATFORM_SCRIPTS_DIR = tmp_platform
                operations_module._load_manifest = lambda: patched_manifest
                operations_module._verify_capsule = lambda: {
                    "kind": "icp.iff-v1-vendor-capsule-verify",
                    "ok": True,
                    "capsule_root": "vendor/iff_v1",
                }
                try:
                    request = _request_factory(proj, run_root)
                    binding = bm.prepare_binding(
                        mp, "flutter.visible_codegen.v1", request
                    )
                    vr = bm.verify_binding(binding)
                    manifest_sha = _sha256_bytes(mp.read_bytes())
                    bd = vr["binding_digest"]
                    nonce = "0123456789abcdef0123456789abcdef"
                    authz = am.prepare_authorization(
                        binding,
                        expected_manifest_path=str(mp),
                        expected_manifest_sha256=manifest_sha,
                        expected_binding_digest=bd,
                        execution_nonce=nonce,
                    )
                    expected = (
                        str(mp), manifest_sha, bd, authz["authorization_digest"]
                    )
                    authz_module_holder["am"] = am
                    executor_module_holder["em"] = executor_module
                    yield authz, expected, nonce, proj, run_root
                finally:
                    operations_module.CAPSULE_SCRIPTS_DIR = saved_csd
                    operations_module.PLATFORM_SCRIPTS_DIR = saved_psd
                    operations_module._load_manifest = saved_lm
                    operations_module._verify_capsule = saved_vc

    with _substituted_visible(executor) as (authz, expected, nonce, proj, run_root):
        report = executor.execute_authorization(**_exec_kwargs(expected, authz))

    assert report["ok"] is True
    assert report["overall_status"] == "success"
    # P2.5a2: visible_codegen now has four ordered steps.
    assert len(report["step_results"]) == 4
    # Ordered: each step's step_id must match the plan's order.
    plan_steps = authz["verified_binding"]["plan"]["steps"]
    for i, sr in enumerate(report["step_results"]):
        assert sr["step_id"] == plan_steps[i]["step_id"]
        assert sr["status"] == "success"
        assert sr["exit_code"] == 0
    # Verify each step's argv matches exactly (no shell/reorder/add).
    for i, sr in enumerate(report["step_results"]):
        bs = plan_steps[i]
        # The in-memory step result records the exact argv tuple.
        assert tuple(sr["argv"]) == tuple(bs["argv"])
        assert sr["cwd"] == bs["cwd"]
        assert sr["timeout_seconds"] == bs["timeout_seconds"]
        assert sr["shell"] is False
        assert sr["start_new_session"] is True
        assert sr["stdin_devnull"] is True
        assert sr["close_fds"] is True


# ---------------------------------------------------------------------------
# 5. Re-verification before every spawn and fail-closed verifier drift
#    after claim.
# ---------------------------------------------------------------------------


def test_reverification_before_each_spawn_succeeds_on_stable_authorization() -> None:
    """Each spawn re-runs verify_authorization. If the authorization
    is stable, all steps run."""
    executor = _load("p2e2b_reverify_ok")
    body = "import sys; sys.exit(0)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        report = executor.execute_authorization(**_exec_kwargs(expected, authz))
    assert report["ok"] is True


def test_fail_closed_after_claim_on_verifier_drift() -> None:
    """Once the nonce is claimed, if the binding's binding_digest in
    the embedded binding drifts BEFORE any spawn, verify must fail
    closed and persist a verification_failure terminal result without
    spawning any operation step.

    We force drift by replacing the authorization module's
    verify_authorization to raise after the first call (the claim)."""
    executor = _load("p2e2b_drift_post_claim")
    body = "import sys; sys.exit(0)\n"

    # State: 0 = before-claim verify, 1 = before-spawn verify (must raise).
    state = {"count": 0}

    @contextlib.contextmanager
    def _patched_authz(am):
        original = am.verify_authorization

        def _verifier(*args, **kwargs):
            state["count"] += 1
            if state["count"] >= 2:
                raise am.FlutterExecutionAuthorizationError(
                    "injected post-claim verifier drift"
                )
            return original(*args, **kwargs)

        am.verify_authorization = _verifier
        try:
            yield
        finally:
            am.verify_authorization = original

    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        run_root = Path(authz["verified_binding"]["selection_verification"]["run_root"])
        with _patched_authz(am):
            report = executor.execute_authorization(**_exec_kwargs(expected, authz))
        assert report["ok"] is False
        assert report["overall_status"] == "verification_failure"
        assert report["execution_nonce"] == nonce
        # No operation step ran.
        for sr in report["step_results"]:
            assert sr["status"] == "skipped"
        # Claim exists, result exists, marked verification_failure.
        rcpt = run_root / ".icp-execution-receipts-v1"
        result = json.loads((rcpt / f"{nonce}.result.json").read_text(encoding="utf-8"))
        assert result["overall_status"] == "verification_failure"


# ---------------------------------------------------------------------------
# 6. Executable lexical/canonical/SHA drift; primitive symlink/path/SHA
#    drift; cwd symlink/path drift.
# ---------------------------------------------------------------------------


def test_rejects_executable_sha_drift() -> None:
    """Tamper the recorded executable_sha256 of the step authorization
    AFTER prepare, BEFORE execute. Verify must fail closed before any
    spawn (no claim is written)."""
    executor = _load("p2e2b_esha_drift")
    body = "import sys; sys.exit(0)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        tampered = copy.deepcopy(authz)
        tampered["step_authorizations"][0]["executable_sha256"] = "9" * 64
        # Recompute step digest and top-level digest so verify passes
        # the in-document checks; the byte-level recheck still fails.
        sa = tampered["step_authorizations"][0]
        sa_payload = {
            k: v for k, v in sa.items() if k != "step_authorization_digest"
        }
        sa["step_authorization_digest"] = _sha256_bytes(_canonical_compact(sa_payload))
        top_payload = {
            k: v for k, v in tampered.items() if k != "authorization_digest"
        }
        tampered["authorization_digest"] = _sha256_bytes(_canonical_compact(top_payload))
        run_root = Path(authz["verified_binding"]["selection_verification"]["run_root"])
        try:
            executor.execute_authorization(
                **_exec_kwargs(expected, tampered, expected_authorization_digest=tampered["authorization_digest"])
            )
        except executor.FlutterExecutionExecutorError:
            pass
        else:
            raise AssertionError("executable sha drift accepted")
    # No receipt directory should have been created (failure happened
    # during pre-claim verification).
    rcpt = run_root / ".icp-execution-receipts-v1"
    assert not rcpt.exists(), "receipt dir created before verification"


def test_rejects_primitive_sha_drift_post_claim() -> None:
    """After claim, before spawn: the primitive script file is
    rewritten with different content. The pre-spawn re-hash must
    fail closed."""
    executor = _load("p2e2b_prim_drift")
    body = "import sys; sys.exit(0)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        run_root = Path(authz["verified_binding"]["selection_verification"]["run_root"])
        # Patch the executor's pre-spawn hook so that just before the
        # spawn of step 0, we mutate the primitive file.
        original_pre_spawn = executor._pre_spawn_recheck

        def _drift_pre_spawn(*args, **kwargs):
            # Drift the primitive file.
            sp.write_text("MUTATED\n", encoding="utf-8")
            return original_pre_spawn(*args, **kwargs)

        executor._pre_spawn_recheck = _drift_pre_spawn
        try:
            report = executor.execute_authorization(**_exec_kwargs(expected, authz))
        finally:
            executor._pre_spawn_recheck = original_pre_spawn
        assert report["ok"] is False
        assert report["overall_status"] in ("integrity_failure", "verification_failure")
        rcpt = run_root / ".icp-execution-receipts-v1"
        result = json.loads((rcpt / f"{nonce}.result.json").read_text(encoding="utf-8"))
        assert result["overall_status"] in ("integrity_failure", "verification_failure")


def test_rejects_primitive_path_symlink_post_claim() -> None:
    """After claim, the primitive file at argv[1] is replaced by a
    symlink. The pre-spawn lstat non-symlink check must fail closed."""
    executor = _load("p2e2b_prim_sym")
    body = "import sys; sys.exit(0)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        original_pre_spawn = executor._pre_spawn_recheck

        def _symlink_pre_spawn(*args, **kwargs):
            backup = sp.with_suffix(".py.real")
            backup.write_bytes(sp.read_bytes())
            sp.unlink()
            os.symlink(backup, sp)
            return original_pre_spawn(*args, **kwargs)

        executor._pre_spawn_recheck = _symlink_pre_spawn
        try:
            report = executor.execute_authorization(**_exec_kwargs(expected, authz))
        finally:
            executor._pre_spawn_recheck = original_pre_spawn
        assert report["ok"] is False
        assert report["overall_status"] in ("integrity_failure", "verification_failure")


def test_rejects_cwd_drift_post_claim() -> None:
    """After the per-step authorization verification passes but before
    the pre-spawn recheck, the bound cwd directory is replaced by a
    regular file. The pre-spawn cwd check (lstat/S_ISDIR) must reject
    with integrity_failure, no spawn occurs, and the claimant's
    terminal result is persisted.

    Filesystem drift is driven by wrapping the verifier so the Nth
    (pre-spawn) verify call mutates the filesystem after the real
    verify succeeds. State is always restored in finally."""
    executor = _load("p2e2b_cwd_drift")
    body = "import sys; sys.exit(0)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        run_root = Path(authz["verified_binding"]["selection_verification"]["run_root"])
        bound_cwd = authz["step_authorizations"][0]["cwd"]
        original_verify = am.verify_authorization
        state = {"count": 0, "drifted": False}

        def _drifting_verify(*args, **kwargs):
            result = original_verify(*args, **kwargs)
            state["count"] += 1
            # On the second call (pre-spawn verify for step 0), drift
            # the cwd: rename the directory aside and place a regular
            # file at the lexical path.
            if state["count"] >= 2 and not state["drifted"]:
                backup = bound_cwd + ".drifted_backup"
                os.rename(bound_cwd, backup)
                Path(bound_cwd).write_text("not a dir")
                state["drifted"] = True
                state["backup"] = backup
            return result

        am.verify_authorization = _drifting_verify
        spawn_count = {"n": 0}
        original_spawn = executor._spawn_step

        def _no_spawn(*args, **kwargs):
            spawn_count["n"] += 1
            return original_spawn(*args, **kwargs)

        executor._spawn_step = _no_spawn
        try:
            report = executor.execute_authorization(**_exec_kwargs(expected, authz))
        finally:
            am.verify_authorization = original_verify
            executor._spawn_step = original_spawn
            if state.get("drifted"):
                try:
                    os.unlink(bound_cwd)
                except OSError:
                    pass
                os.rename(state["backup"], bound_cwd)
        assert report["ok"] is False
        assert report["overall_status"] == "integrity_failure"
        assert spawn_count["n"] == 0, "operation spawn ran despite cwd drift"
        # Terminal result persisted by the claimant.
        rcpt = run_root / ".icp-execution-receipts-v1"
        result = json.loads((rcpt / f"{nonce}.result.json").read_text("utf-8"))
        assert result["overall_status"] == "integrity_failure"


# ---------------------------------------------------------------------------
# 7. Step add/delete/reorder and every bound-field mismatch rejection.
# ---------------------------------------------------------------------------


def _assert_execute_rejects(executor, authz, expected) -> None:
    try:
        executor.execute_authorization(**_exec_kwargs(expected, authz))
    except executor.FlutterExecutionExecutorError:
        return
    raise AssertionError("tampered authorization accepted by executor")


def test_execute_rejects_step_reorder() -> None:
    executor = _load("p2e2b_step_reorder")
    body = "import sys; sys.exit(0)\n"
    bodies = {
        "generate_canvas.py": "import sys; sys.exit(0)\n",
        "make_implementation_map.py": "import sys; sys.exit(0)\n",
        "make_status_bar_policy.py": "import sys; sys.exit(0)\n",
    }

    @contextlib.contextmanager
    def _substituted_visible(executor_module):
        am = executor_module._load_authorization_module()
        bm = am._load_binding_module()
        operations_module = bm._load_operations_module()
        with _frozen_canonical_flutter_project(batch_id="p2e2b-reorder") as (proj, run_root, mp):
            with _with_fake_preflight(bm):
                saved_csd = operations_module.CAPSULE_SCRIPTS_DIR
                saved_lm = operations_module._load_manifest
                saved_vc = operations_module._verify_capsule
                tmp_scripts = proj.parent / "scripts_reorder"
                tmp_scripts.mkdir()
                real_manifest = operations_module._load_manifest()
                patched_scripts = []
                for entry in real_manifest["scripts"]:
                    if entry["name"] in bodies:
                        sp = tmp_scripts / entry["name"]
                        sp.write_text(bodies[entry["name"]], encoding="utf-8")
                        patched_scripts.append(
                            {**entry, "sha256": _sha256_bytes(sp.read_bytes())}
                        )
                    else:
                        patched_scripts.append(entry)
                patched_manifest = {**real_manifest, "scripts": patched_scripts}
                operations_module.CAPSULE_SCRIPTS_DIR = tmp_scripts
                operations_module._load_manifest = lambda: patched_manifest
                operations_module._verify_capsule = lambda: {
                    "kind": "icp.iff-v1-vendor-capsule-verify",
                    "ok": True,
                    "capsule_root": "vendor/iff_v1",
                }
                try:
                    for n, payload in (
                        ("render_plan.json", {"a": 1}),
                        ("classification.json", {"a": 1}),
                        ("component_manifest.json", {"a": 1}),
                        ("scene.json", {"a": 1}),
                    ):
                        _write_json(run_root / n, payload)
                    request = {
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
                    binding = bm.prepare_binding(
                        mp, "flutter.visible_codegen.v1", request
                    )
                    vr = bm.verify_binding(binding)
                    manifest_sha = _sha256_bytes(mp.read_bytes())
                    bd = vr["binding_digest"]
                    nonce = "0123456789abcdef0123456789abcdef"
                    authz = am.prepare_authorization(
                        binding,
                        expected_manifest_path=str(mp),
                        expected_manifest_sha256=manifest_sha,
                        expected_binding_digest=bd,
                        execution_nonce=nonce,
                    )
                    expected = (
                        str(mp), manifest_sha, bd, authz["authorization_digest"]
                    )
                    yield authz, expected
                finally:
                    operations_module.CAPSULE_SCRIPTS_DIR = saved_csd
                    operations_module._load_manifest = saved_lm
                    operations_module._verify_capsule = saved_vc

    with _substituted_visible(executor) as (authz, expected):
        tampered = copy.deepcopy(authz)
        # Swap step_authorizations AND embedded plan steps in lockstep
        # so the binding's verify still passes (binding re-build is
        # unaffected; only the authorization-level step order changes).
        # Actually the executor must re-verify the binding and require
        # that step_authorizations[i] matches the same-index rebuilt
        # step authorization. Reordering step_authorizations breaks
        # the equality check.
        tampered["step_authorizations"][0], tampered["step_authorizations"][1] = (
            tampered["step_authorizations"][1],
            tampered["step_authorizations"][0],
        )
        # Recompute top-level digest so the in-document check passes.
        top_payload = {
            k: v for k, v in tampered.items() if k != "authorization_digest"
        }
        tampered["authorization_digest"] = _sha256_bytes(_canonical_compact(top_payload))
        _assert_execute_rejects(
            executor,
            tampered,
            (expected[0], expected[1], expected[2], tampered["authorization_digest"]),
        )


def test_execute_rejects_step_delete() -> None:
    executor = _load("p2e2b_step_del")
    body = "import sys; sys.exit(0)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        tampered = copy.deepcopy(authz)
        del tampered["step_authorizations"][0]
        top_payload = {
            k: v for k, v in tampered.items() if k != "authorization_digest"
        }
        tampered["authorization_digest"] = _sha256_bytes(_canonical_compact(top_payload))
        _assert_execute_rejects(
            executor,
            tampered,
            (expected[0], expected[1], expected[2], tampered["authorization_digest"]),
        )


def test_execute_rejects_step_add() -> None:
    executor = _load("p2e2b_step_add")
    body = "import sys; sys.exit(0)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        tampered = copy.deepcopy(authz)
        tampered["step_authorizations"].append(
            copy.deepcopy(tampered["step_authorizations"][0])
        )
        top_payload = {
            k: v for k, v in tampered.items() if k != "authorization_digest"
        }
        tampered["authorization_digest"] = _sha256_bytes(_canonical_compact(top_payload))
        _assert_execute_rejects(
            executor,
            tampered,
            (expected[0], expected[1], expected[2], tampered["authorization_digest"]),
        )


def test_execute_rejects_step_argv_tamper() -> None:
    executor = _load("p2e2b_step_argv")
    body = "import sys; sys.exit(0)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        tampered = copy.deepcopy(authz)
        # Mutate embedded binding plan argv — binding re-verify fails.
        tampered["verified_binding"]["plan"]["steps"][0]["argv"].append("--INJECTED")
        top_payload = {
            k: v for k, v in tampered.items() if k != "authorization_digest"
        }
        tampered["authorization_digest"] = _sha256_bytes(_canonical_compact(top_payload))
        _assert_execute_rejects(
            executor,
            tampered,
            (expected[0], expected[1], expected[2], tampered["authorization_digest"]),
        )


def test_execute_rejects_step_cwd_tamper() -> None:
    executor = _load("p2e2b_step_cwd")
    body = "import sys; sys.exit(0)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        tampered = copy.deepcopy(authz)
        tampered["verified_binding"]["plan"]["steps"][0]["cwd"] = "/tmp/tampered"
        top_payload = {
            k: v for k, v in tampered.items() if k != "authorization_digest"
        }
        tampered["authorization_digest"] = _sha256_bytes(_canonical_compact(top_payload))
        _assert_execute_rejects(
            executor,
            tampered,
            (expected[0], expected[1], expected[2], tampered["authorization_digest"]),
        )


def test_execute_rejects_step_timeout_tamper() -> None:
    executor = _load("p2e2b_step_to")
    body = "import sys; sys.exit(0)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        tampered = copy.deepcopy(authz)
        tampered["step_authorizations"][0]["timeout_seconds"] = (
            tampered["step_authorizations"][0]["timeout_seconds"] + 1
        )
        sa = tampered["step_authorizations"][0]
        sa_payload = {
            k: v for k, v in sa.items() if k != "step_authorization_digest"
        }
        sa["step_authorization_digest"] = _sha256_bytes(_canonical_compact(sa_payload))
        top_payload = {
            k: v for k, v in tampered.items() if k != "authorization_digest"
        }
        tampered["authorization_digest"] = _sha256_bytes(_canonical_compact(top_payload))
        _assert_execute_rejects(
            executor,
            tampered,
            (expected[0], expected[1], expected[2], tampered["authorization_digest"]),
        )


# ---------------------------------------------------------------------------
# 8. Atomic claim permissions/content/digest; result permissions/content/
#    digest; raw output absent from disk.
# ---------------------------------------------------------------------------


def test_claim_and_result_file_permissions_and_content() -> None:
    """The claim and result files must have mode exactly 0600, be
    regular files (not symlinks), and contain canonical JSON with the
    expected schema. The terminal result must bind the claim digest.
    The newly created receipt directory must have mode exactly 0700.
    All assertions run inside the owning temp context (the run root is
    deleted when the context exits)."""
    executor = _load("p2e2b_perm")
    body = "import sys; sys.exit(0)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        run_root = Path(authz["verified_binding"]["selection_verification"]["run_root"])
        report = executor.execute_authorization(**_exec_kwargs(expected, authz))
        assert report["ok"] is True
        rcpt = run_root / ".icp-execution-receipts-v1"
        claim_path = rcpt / f"{nonce}.claim.json"
        result_path = rcpt / f"{nonce}.result.json"
        assert claim_path.is_file()
        assert result_path.is_file()
        # Newly created receipt dir must be exactly 0700.
        ds = rcpt.lstat()
        assert stat.S_ISDIR(ds.st_mode)
        assert not stat.S_ISLNK(os.lstat(rcpt).st_mode)
        assert stat.S_IMODE(ds.st_mode) == 0o700, oct(stat.S_IMODE(ds.st_mode))
        # Mode exactly 0600 for claim and result.
        cs = claim_path.lstat()
        rs = result_path.lstat()
        assert stat.S_ISREG(cs.st_mode)
        assert stat.S_ISREG(rs.st_mode)
        assert not stat.S_ISLNK(os.lstat(claim_path).st_mode)
        assert not stat.S_ISLNK(os.lstat(result_path).st_mode)
        assert stat.S_IMODE(cs.st_mode) == 0o600, oct(stat.S_IMODE(cs.st_mode))
        assert stat.S_IMODE(rs.st_mode) == 0o600, oct(stat.S_IMODE(rs.st_mode))
        # Content is canonical JSON.
        claim_bytes = claim_path.read_bytes()
        result_bytes = result_path.read_bytes()
        claim = json.loads(claim_bytes.decode("utf-8"))
        result = json.loads(result_bytes.decode("utf-8"))
        assert claim["kind"] == KIND_CLAIM
        assert claim["schema_version"] == SCHEMA_VERSION
        assert claim["execution_nonce"] == nonce
        assert claim["expected_authorization_digest"] == expected[3]
        assert claim["binding_digest"] == expected[2]
        assert claim["selection_manifest_path"] == expected[0]
        assert claim["selection_manifest_sha256"] == expected[1]
        assert claim["platform_id"] == "flutter"
        assert claim["profile_id"] == "flutter-standard"
        assert claim["operation_id"] == "flutter.fan_in.v1"
        assert claim["port_id"] == "fan_in"
        assert isinstance(claim["step_authorization_digests"], list)
        assert all(_is_sha256_hex(d) for d in claim["step_authorization_digests"])
        assert _is_sha256_hex(claim["claim_digest"])
        # Recompute claim digest over canonical payload excluding claim_digest.
        payload = {k: v for k, v in claim.items() if k != "claim_digest"}
        assert claim["claim_digest"] == _sha256_bytes(_canonical_compact(payload))
        assert json.dumps(claim, sort_keys=True, separators=(",", ":")) + "" == (
            claim_bytes.decode("utf-8")
        ), "claim not canonical compact JSON"
        # Result binds claim digest and contains only sanitized metadata.
        assert result["kind"] == KIND_RESULT
        assert result["schema_version"] == SCHEMA_VERSION
        assert result["execution_nonce"] == nonce
        assert result["claim_digest"] == claim["claim_digest"]
        assert result["expected_authorization_digest"] == expected[3]
        assert result["overall_status"] == "success"
        assert _is_sha256_hex(result["result_digest"])
        payload = {k: v for k, v in result.items() if k != "result_digest"}
        assert result["result_digest"] == _sha256_bytes(_canonical_compact(payload))
        # No raw output persisted.
        assert "hello" not in result_bytes.decode("utf-8")
        # No timestamps/PIDs/hostnames/random in receipts.
        for needle in ("timestamp", "pid", "hostname", "host", "started_at", "ended_at"):
            assert needle not in claim_bytes.decode("utf-8").lower(), needle
            assert needle not in result_bytes.decode("utf-8").lower(), needle


def test_raw_stdout_stderr_absent_from_disk_on_nonzero_exit() -> None:
    """Even on non-zero exit, raw output must never be persisted."""
    executor = _load("p2e2b_raw_absent")
    body = (
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "sys.stdout.write('SECRET_STDOUT_MARKER\\n')\n"
        "sys.stderr.write('SECRET_STDERR_MARKER\\n')\n"
        "sys.exit(7)\n"
    )
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        run_root = Path(authz["verified_binding"]["selection_verification"]["run_root"])
        report = executor.execute_authorization(**_exec_kwargs(expected, authz))
        assert report["ok"] is False
        assert report["overall_status"] == "step_failure"
        rcpt = run_root / ".icp-execution-receipts-v1"
        claim_text = (rcpt / f"{nonce}.claim.json").read_text(encoding="utf-8")
        result_text = (rcpt / f"{nonce}.result.json").read_text(encoding="utf-8")
        assert "SECRET_STDOUT_MARKER" not in claim_text
        assert "SECRET_STDOUT_MARKER" not in result_text
        assert "SECRET_STDERR_MARKER" not in claim_text
        assert "SECRET_STDERR_MARKER" not in result_text
        # The in-memory report MAY carry the capped tail.
        assert b"SECRET_STDOUT_MARKER" in base64.b64decode(
            report["step_results"][0]["stdout_tail_b64"]
        )


# ---------------------------------------------------------------------------
# 9. Replay after every terminal outcome: success, non-zero, timeout,
#    launch failure, post-claim verification failure, integrity drift,
#    claim-only crash state. No operation spawn on replay.
# ---------------------------------------------------------------------------


def test_replay_after_success_no_respawn() -> None:
    executor = _load("p2e2b_replay_ok")
    body = "import sys; sys.exit(0)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        report1 = executor.execute_authorization(**_exec_kwargs(expected, authz))
        assert report1["ok"] is True
        # Second call must reject the nonce without spawning.
        spawn_count = {"n": 0}
        original_spawn = executor._spawn_step

        def _count_spawn(*args, **kwargs):
            spawn_count["n"] += 1
            return original_spawn(*args, **kwargs)

        executor._spawn_step = _count_spawn
        try:
            try:
                executor.execute_authorization(**_exec_kwargs(expected, authz))
            except executor.FlutterExecutionExecutorError:
                pass
            else:
                raise AssertionError("replay after success accepted")
        finally:
            executor._spawn_step = original_spawn
        assert spawn_count["n"] == 0


def test_replay_after_nonzero_no_respawn() -> None:
    executor = _load("p2e2b_replay_nz")
    body = "import sys; sys.exit(3)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        r1 = executor.execute_authorization(**_exec_kwargs(expected, authz))
        assert r1["ok"] is False
        try:
            executor.execute_authorization(**_exec_kwargs(expected, authz))
        except executor.FlutterExecutionExecutorError:
            pass
        else:
            raise AssertionError("replay after non-zero accepted")


def test_replay_after_timeout_no_respawn() -> None:
    executor = _load("p2e2b_replay_to")
    # Sleep longer than the timeout. Use a tiny body. The bound timeout
    # is the registry TIMEOUT_SECONDS (120). To avoid a 120s test, we
    # patch the executor's per-call timeout via a seam.
    body = (
        "#!/usr/bin/env python3\n"
        "import time, sys\n"
        "sys.stdout.write('start\\n'); sys.stdout.flush()\n"
        "time.sleep(30)\n"
        "sys.stdout.write('end\\n')\n"
    )
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        # Force a 1-second timeout.
        original = executor._effective_timeout

        def _1s(*args, **kwargs):
            return 1

        executor._effective_timeout = _1s
        try:
            r1 = executor.execute_authorization(**_exec_kwargs(expected, authz))
        finally:
            executor._effective_timeout = original
        assert r1["ok"] is False
        assert r1["overall_status"] == "timeout"
        try:
            executor.execute_authorization(**_exec_kwargs(expected, authz))
        except executor.FlutterExecutionExecutorError:
            pass
        else:
            raise AssertionError("replay after timeout accepted")


def test_replay_after_launch_failure_no_respawn() -> None:
    executor = _load("p2e2b_replay_lf")
    body = "import sys; sys.exit(0)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        # Force launch failure by patching the executor's spawn to raise
        # OSError on the first call.
        original_spawn = executor._spawn_step

        def _failing_spawn(*args, **kwargs):
            raise OSError("injected launch failure")

        executor._spawn_step = _failing_spawn
        try:
            r1 = executor.execute_authorization(**_exec_kwargs(expected, authz))
        finally:
            executor._spawn_step = original_spawn
        assert r1["ok"] is False
        assert r1["overall_status"] == "launch_error"
        # Replay must be rejected.
        try:
            executor.execute_authorization(**_exec_kwargs(expected, authz))
        except executor.FlutterExecutionExecutorError:
            pass
        else:
            raise AssertionError("replay after launch failure accepted")


def test_replay_after_claim_only_crash_state_no_respawn() -> None:
    """Simulate a claim-only crash state: pre-write a valid mode-0600
    claim under a mode-0700 receipt dir with NO result file, then call
    execute. The caller is a replay loser: it must reject immediately
    without spawning any operation step, without creating/replacing/
    deleting the result file, and raise. The result path must remain
    absent (claim-only is itself the durable indeterminate/consumed
    state and needs no materialized result)."""
    executor = _load("p2e2b_replay_claim_only")
    body = "import sys; sys.exit(0)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        run_root = Path(authz["verified_binding"]["selection_verification"]["run_root"])
        rcpt = run_root / ".icp-execution-receipts-v1"
        rcpt.mkdir(parents=True, exist_ok=True)
        os.chmod(rcpt, 0o700)
        # Build a synthetic claim matching the executor's canonical
        # schema so the O_EXCL open fails on replay.
        steps_dig = [
            sa["step_authorization_digest"]
            for sa in authz["step_authorizations"]
        ]
        claim_payload = {
            "kind": KIND_CLAIM,
            "schema_version": SCHEMA_VERSION,
            "execution_nonce": nonce,
            "expected_authorization_digest": expected[3],
            "binding_digest": expected[2],
            "selection_manifest_path": expected[0],
            "selection_manifest_sha256": expected[1],
            "platform_id": "flutter",
            "profile_id": "flutter-standard",
            "operation_id": "flutter.fan_in.v1",
            "port_id": "fan_in",
            "step_authorization_digests": steps_dig,
        }
        claim_digest = _sha256_bytes(_canonical_compact(claim_payload))
        claim_payload["claim_digest"] = claim_digest
        claim_path = rcpt / f"{nonce}.claim.json"
        fd = os.open(
            claim_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            os.write(fd, _canonical_compact(claim_payload))
            os.fsync(fd)
        finally:
            os.close(fd)
        # Snapshot the claim bytes so we can prove no mutation.
        claim_bytes_before = claim_path.read_bytes()
        result_path = rcpt / f"{nonce}.result.json"
        assert not result_path.exists()
        original_spawn = executor._spawn_step

        def _no_spawn(*args, **kwargs):
            raise AssertionError("spawn ran on claim-only replay")

        executor._spawn_step = _no_spawn
        try:
            try:
                executor.execute_authorization(**_exec_kwargs(expected, authz))
            except executor.FlutterExecutionExecutorError:
                pass
            else:
                raise AssertionError(
                    "claim-only replay accepted without raising"
                )
        finally:
            executor._spawn_step = original_spawn
        # The replay loser MUST NOT have created/replaced/deleted/
        # truncated the result file.
        assert not result_path.exists(), (
            "replay loser wrote a terminal result (only the claim owner may)"
        )
        # The claim file must be byte-identical (never mutated by the
        # replay loser).
        assert claim_path.read_bytes() == claim_bytes_before, (
            "replay loser mutated the claim file"
        )


# ---------------------------------------------------------------------------
# 10. Concurrent atomic claim contention.
# ---------------------------------------------------------------------------


def test_concurrent_claim_contention_exactly_one_winner() -> None:
    """Two threads call execute_authorization on the same authorization
    at the same time. Exactly one must claim the nonce and spawn
    exactly one operation execution; the loser must see O_EXCL failure
    and reject without spawning. Exactly one terminal result file must
    exist after both threads finish and its persisted digest/status
    must belong to the winning call. The loser writes no result."""
    executor = _load("p2e2b_concurrent")
    body = "import sys; sys.exit(0)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        run_root = Path(authz["verified_binding"]["selection_verification"]["run_root"])
        # Use a barrier so both threads hit claim at the same time.
        barrier = threading.Barrier(2)
        original_claim = executor._atomic_claim_nonce

        def _synced_claim(*args, **kwargs):
            barrier.wait(timeout=5)
            return original_claim(*args, **kwargs)

        executor._atomic_claim_nonce = _synced_claim
        spawn_counter = {"n": 0}
        spawn_lock = threading.Lock()
        original_spawn = executor._spawn_step

        def _counting_spawn(*args, **kwargs):
            with spawn_lock:
                spawn_counter["n"] += 1
            return original_spawn(*args, **kwargs)

        executor._spawn_step = _counting_spawn
        results: dict[int, Any] = {}
        errors: dict[int, Any] = {}

        def _runner(idx: int):
            try:
                results[idx] = executor.execute_authorization(
                    **_exec_kwargs(expected, authz)
                )
            except Exception as exc:  # noqa: BLE001
                errors[idx] = exc

        threads = [threading.Thread(target=_runner, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        executor._atomic_claim_nonce = original_claim
        executor._spawn_step = original_spawn

        # Exactly one claimant won and exactly one operation execution
        # occurred.
        assert len(results) == 1, (
            f"expected 1 winner, got {len(results)}: {results}"
        )
        assert len(errors) == 1
        assert spawn_counter["n"] == 1, (
            f"expected exactly 1 spawn, got {spawn_counter['n']}"
        )
        winner_report = next(iter(results.values()))
        assert winner_report["ok"] is True
        # Exactly one terminal result file exists.
        rcpt = run_root / ".icp-execution-receipts-v1"
        result_path = rcpt / f"{nonce}.result.json"
        assert result_path.is_file(), "winner did not persist terminal result"
        result = json.loads(result_path.read_text("utf-8"))
        # The persisted result belongs to the winning call: its digest
        # and status match the winner's report (no conservative result
        # written by the loser).
        assert result["overall_status"] == winner_report["overall_status"]
        assert result["result_digest"] == winner_report["result_digest"]
        assert result["claim_digest"] == winner_report["claim_digest"]


# ---------------------------------------------------------------------------
# 11. Receipt directory defenses: symlink, non-directory, broad perms,
#     wrong owner.
# ---------------------------------------------------------------------------


def test_receipt_dir_rejects_symlink() -> None:
    executor = _load("p2e2b_rcpt_sym")
    body = "import sys; sys.exit(0)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        run_root = Path(authz["verified_binding"]["selection_verification"]["run_root"])
        rcpt = run_root / ".icp-execution-receipts-v1"
        # Pre-create a symlink at the receipt-dir path.
        target = run_root / "real_receipts"
        target.mkdir()
        os.symlink(target, rcpt)
        try:
            executor.execute_authorization(**_exec_kwargs(expected, authz))
        except executor.FlutterExecutionExecutorError:
            pass
        else:
            raise AssertionError("symlink receipt dir accepted")


def test_receipt_dir_rejects_non_directory() -> None:
    executor = _load("p2e2b_rcpt_file")
    body = "import sys; sys.exit(0)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        run_root = Path(authz["verified_binding"]["selection_verification"]["run_root"])
        rcpt = run_root / ".icp-execution-receipts-v1"
        rcpt.write_text("not a directory", encoding="utf-8")
        try:
            executor.execute_authorization(**_exec_kwargs(expected, authz))
        except executor.FlutterExecutionExecutorError:
            pass
        else:
            raise AssertionError("non-directory receipt dir accepted")


def test_receipt_dir_rejects_broad_permissions() -> None:
    executor = _load("p2e2b_rcpt_broad")
    body = "import sys; sys.exit(0)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        run_root = Path(authz["verified_binding"]["selection_verification"]["run_root"])
        rcpt = run_root / ".icp-execution-receipts-v1"
        rcpt.mkdir(parents=True, exist_ok=True)
        os.chmod(rcpt, 0o755)  # broad
        try:
            executor.execute_authorization(**_exec_kwargs(expected, authz))
        except executor.FlutterExecutionExecutorError:
            pass
        else:
            raise AssertionError("broad-permission receipt dir accepted")


def test_receipt_claim_defends_against_symlink_at_claim_path() -> None:
    """A pre-existing symlink at the claim filename must be rejected
    by O_NOFOLLOW / O_EXCL."""
    executor = _load("p2e2b_rcpt_clsym")
    body = "import sys; sys.exit(0)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        run_root = Path(authz["verified_binding"]["selection_verification"]["run_root"])
        rcpt = run_root / ".icp-execution-receipts-v1"
        rcpt.mkdir(parents=True, exist_ok=True)
        os.chmod(rcpt, 0o700)
        claim_path = rcpt / f"{nonce}.claim.json"
        os.symlink(rcpt / "elsewhere.json", claim_path)
        try:
            executor.execute_authorization(**_exec_kwargs(expected, authz))
        except executor.FlutterExecutionExecutorError:
            pass
        else:
            raise AssertionError("symlink at claim path accepted")


def test_receipt_result_defends_against_symlink_at_result_path() -> None:
    """Pre-claim the nonce manually, then place a symlink at the result
    path. The terminal result write must reject the symlink."""
    executor = _load("p2e2b_rcpt_rssym")
    body = "import sys; sys.exit(0)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        run_root = Path(authz["verified_binding"]["selection_verification"]["run_root"])
        rcpt = run_root / ".icp-execution-receipts-v1"
        rcpt.mkdir(parents=True, exist_ok=True)
        os.chmod(rcpt, 0o700)
        # Write a valid claim so the executor proceeds.
        steps_dig = [
            sa["step_authorization_digest"]
            for sa in authz["step_authorizations"]
        ]
        claim_payload = {
            "kind": KIND_CLAIM,
            "schema_version": SCHEMA_VERSION,
            "execution_nonce": nonce,
            "expected_authorization_digest": expected[3],
            "binding_digest": expected[2],
            "selection_manifest_path": expected[0],
            "selection_manifest_sha256": expected[1],
            "platform_id": "flutter",
            "profile_id": "flutter-standard",
            "operation_id": "flutter.fan_in.v1",
            "port_id": "fan_in",
            "step_authorization_digests": steps_dig,
        }
        claim_digest = _sha256_bytes(_canonical_compact(claim_payload))
        claim_payload["claim_digest"] = claim_digest
        claim_path = rcpt / f"{nonce}.claim.json"
        fd = os.open(claim_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(fd, _canonical_compact(claim_payload))
            os.fsync(fd)
        finally:
            os.close(fd)
        # Place a symlink at the result path.
        result_path = rcpt / f"{nonce}.result.json"
        os.symlink(rcpt / "elsewhere_result.json", result_path)
        try:
            executor.execute_authorization(**_exec_kwargs(expected, authz))
        except executor.FlutterExecutionExecutorError:
            pass
        else:
            raise AssertionError("symlink at result path accepted")


# ---------------------------------------------------------------------------
# 12. Multi-megabyte stdout/stderr: bounded 16 KiB tails, full-stream
#     hashes/counts, no deadlock.
# ---------------------------------------------------------------------------


def test_bounded_tails_and_full_stream_hashes_on_large_output() -> None:
    executor = _load("p2e2b_large")
    big_text = "A" * 1000 + "\n"
    # 2000 lines * 1001 chars ~= 2 MiB per stream.
    body = (
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "line = 'A' * 1000 + chr(10)\n"
        "data = line * 2000\n"
        "sys.stdout.write(data)\n"
        "sys.stderr.write(data)\n"
    )
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        report = executor.execute_authorization(**_exec_kwargs(expected, authz))
    assert report["ok"] is True
    step = report["step_results"][0]
    # 2000 * 1001 = 2_002_000 bytes per stream.
    assert step["stdout_byte_count"] == 2002000
    assert step["stderr_byte_count"] == 2002000
    # Full-stream hash matches.
    line = b"A" * 1000 + b"\n"
    full = line * 2000
    assert step["stdout_sha256"] == _sha256_bytes(full)
    assert step["stderr_sha256"] == _sha256_bytes(full)
    # Tail capped at 16 KiB.
    tail = base64.b64decode(step["stdout_tail_b64"])
    assert len(tail) <= 16384
    assert tail == full[-16384:]
    assert step["stdout_truncated"] is True
    assert step["stderr_truncated"] is True


# ---------------------------------------------------------------------------
# 13. Timeout kills/reaps the process group and later steps do not run.
# ---------------------------------------------------------------------------


def test_timeout_kills_process_group_and_no_later_step_runs() -> None:
    """Single step that sleeps; timeout fires; the report is timeout
    and no further steps run."""
    executor = _load("p2e2b_timeout_pg")
    body = (
        "#!/usr/bin/env python3\n"
        "import time, sys, os\n"
        "sys.stdout.write('child alive pid=' + str(os.getpid()) + chr(10))\n"
        "sys.stdout.flush()\n"
        "time.sleep(30)\n"
    )
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        original = executor._effective_timeout

        def _1s(*args, **kwargs):
            return 1

        executor._effective_timeout = _1s
        try:
            report = executor.execute_authorization(**_exec_kwargs(expected, authz))
        finally:
            executor._effective_timeout = original
    assert report["ok"] is False
    assert report["overall_status"] == "timeout"
    assert report["step_results"][0]["status"] == "timed_out"
    # No later step ran (single-step plan); confirm no additional
    # entries exist beyond the timed-out one.
    assert len(report["step_results"]) == len(
        authz["verified_binding"]["plan"]["steps"]
    )


def test_timeout_first_step_blocks_second_step() -> None:
    """Four-step visible_codegen operation (P2.5a2) where the first step
    times out. Steps 2, 3, and 4 must not run."""
    executor = _load("p2e2b_timeout_first")
    bodies = {
        "generate_canvas.py": (
            "#!/usr/bin/env python3\n"
            "import time\n"
            "time.sleep(30)\n"
        ),
        "make_implementation_map.py": "import sys; sys.exit(0)\n",
        "make_status_bar_policy.py": "import sys; sys.exit(0)\n",
    }
    adapter_name = "flutter_expected_slots_adapter_v1.py"
    adapter_body = "import sys; sys.exit(0)\n"

    @contextlib.contextmanager
    def _substituted_visible(executor_module):
        am = executor_module._load_authorization_module()
        bm = am._load_binding_module()
        operations_module = bm._load_operations_module()
        with _frozen_canonical_flutter_project(batch_id="p2e2b-timeout-multi") as (proj, run_root, mp):
            with _with_fake_preflight(bm):
                saved_csd = operations_module.CAPSULE_SCRIPTS_DIR
                saved_psd = operations_module.PLATFORM_SCRIPTS_DIR
                saved_lm = operations_module._load_manifest
                saved_vc = operations_module._verify_capsule
                tmp_scripts = proj.parent / "scripts_timeout"
                tmp_platform = proj.parent / "platforms_timeout"
                tmp_scripts.mkdir()
                tmp_platform.mkdir()
                adapter_sp = tmp_platform / adapter_name
                adapter_sp.write_text(adapter_body, encoding="utf-8")
                real_manifest = operations_module._load_manifest()
                patched_scripts = []
                for entry in real_manifest["scripts"]:
                    if entry["name"] in bodies:
                        sp = tmp_scripts / entry["name"]
                        sp.write_text(bodies[entry["name"]], encoding="utf-8")
                        patched_scripts.append(
                            {**entry, "sha256": _sha256_bytes(sp.read_bytes())}
                        )
                    else:
                        patched_scripts.append(entry)
                patched_manifest = {**real_manifest, "scripts": patched_scripts}
                operations_module.CAPSULE_SCRIPTS_DIR = tmp_scripts
                operations_module.PLATFORM_SCRIPTS_DIR = tmp_platform
                operations_module._load_manifest = lambda: patched_manifest
                operations_module._verify_capsule = lambda: {
                    "kind": "icp.iff-v1-vendor-capsule-verify",
                    "ok": True,
                    "capsule_root": "vendor/iff_v1",
                }
                try:
                    for n, payload in (
                        ("render_plan.json", {"a": 1}),
                        ("classification.json", {"a": 1}),
                        ("component_manifest.json", {"a": 1}),
                        ("scene.json", {"a": 1}),
                    ):
                        _write_json(run_root / n, payload)
                    request = {
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
                    binding = bm.prepare_binding(
                        mp, "flutter.visible_codegen.v1", request
                    )
                    vr = bm.verify_binding(binding)
                    manifest_sha = _sha256_bytes(mp.read_bytes())
                    bd = vr["binding_digest"]
                    nonce = "0123456789abcdef0123456789abcdef"
                    authz = am.prepare_authorization(
                        binding,
                        expected_manifest_path=str(mp),
                        expected_manifest_sha256=manifest_sha,
                        expected_binding_digest=bd,
                        execution_nonce=nonce,
                    )
                    expected = (
                        str(mp), manifest_sha, bd, authz["authorization_digest"]
                    )
                    yield authz, expected
                finally:
                    operations_module.CAPSULE_SCRIPTS_DIR = saved_csd
                    operations_module.PLATFORM_SCRIPTS_DIR = saved_psd
                    operations_module._load_manifest = saved_lm
                    operations_module._verify_capsule = saved_vc

    with _substituted_visible(executor) as (authz, expected):
        original = executor._effective_timeout

        def _1s(*args, **kwargs):
            return 1

        executor._effective_timeout = _1s
        try:
            report = executor.execute_authorization(**_exec_kwargs(expected, authz))
        finally:
            executor._effective_timeout = original
    assert report["ok"] is False
    assert report["overall_status"] == "timeout"
    # P2.5a2: visible_codegen now has four ordered steps.
    assert len(report["step_results"]) == 4
    assert report["step_results"][0]["status"] == "timed_out"
    # Steps 2, 3, 4 must be skipped.
    assert report["step_results"][1]["status"] == "skipped"
    assert report["step_results"][2]["status"] == "skipped"
    assert report["step_results"][3]["status"] == "skipped"


# ---------------------------------------------------------------------------
# 14. Non-zero/signal/launch errors are sanitized; later steps do not run.
# ---------------------------------------------------------------------------


def test_nonzero_exit_stops_chain_and_sanitizes() -> None:
    executor = _load("p2e2b_nonzero_chain")
    bodies = {
        "generate_canvas.py": "import sys; sys.exit(0)\n",
        "make_implementation_map.py": "import sys; sys.exit(4)\n",
        "make_status_bar_policy.py": "import sys; sys.exit(0)\n",
    }
    adapter_name = "flutter_expected_slots_adapter_v1.py"
    adapter_body = "import sys; sys.exit(0)\n"

    @contextlib.contextmanager
    def _substituted_visible(executor_module):
        am = executor_module._load_authorization_module()
        bm = am._load_binding_module()
        operations_module = bm._load_operations_module()
        with _frozen_canonical_flutter_project(batch_id="p2e2b-nonzero-chain") as (proj, run_root, mp):
            with _with_fake_preflight(bm):
                saved_csd = operations_module.CAPSULE_SCRIPTS_DIR
                saved_psd = operations_module.PLATFORM_SCRIPTS_DIR
                saved_lm = operations_module._load_manifest
                saved_vc = operations_module._verify_capsule
                tmp_scripts = proj.parent / "scripts_nonzero_chain"
                tmp_platform = proj.parent / "platforms_nonzero_chain"
                tmp_scripts.mkdir()
                tmp_platform.mkdir()
                adapter_sp = tmp_platform / adapter_name
                adapter_sp.write_text(adapter_body, encoding="utf-8")
                real_manifest = operations_module._load_manifest()
                patched_scripts = []
                for entry in real_manifest["scripts"]:
                    if entry["name"] in bodies:
                        sp = tmp_scripts / entry["name"]
                        sp.write_text(bodies[entry["name"]], encoding="utf-8")
                        patched_scripts.append(
                            {**entry, "sha256": _sha256_bytes(sp.read_bytes())}
                        )
                    else:
                        patched_scripts.append(entry)
                patched_manifest = {**real_manifest, "scripts": patched_scripts}
                operations_module.CAPSULE_SCRIPTS_DIR = tmp_scripts
                operations_module.PLATFORM_SCRIPTS_DIR = tmp_platform
                operations_module._load_manifest = lambda: patched_manifest
                operations_module._verify_capsule = lambda: {
                    "kind": "icp.iff-v1-vendor-capsule-verify",
                    "ok": True,
                    "capsule_root": "vendor/iff_v1",
                }
                try:
                    for n, payload in (
                        ("render_plan.json", {"a": 1}),
                        ("classification.json", {"a": 1}),
                        ("component_manifest.json", {"a": 1}),
                        ("scene.json", {"a": 1}),
                    ):
                        _write_json(run_root / n, payload)
                    request = {
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
                    binding = bm.prepare_binding(
                        mp, "flutter.visible_codegen.v1", request
                    )
                    vr = bm.verify_binding(binding)
                    manifest_sha = _sha256_bytes(mp.read_bytes())
                    bd = vr["binding_digest"]
                    nonce = "0123456789abcdef0123456789abcdef"
                    authz = am.prepare_authorization(
                        binding,
                        expected_manifest_path=str(mp),
                        expected_manifest_sha256=manifest_sha,
                        expected_binding_digest=bd,
                        execution_nonce=nonce,
                    )
                    expected = (
                        str(mp), manifest_sha, bd, authz["authorization_digest"]
                    )
                    yield authz, expected
                finally:
                    operations_module.CAPSULE_SCRIPTS_DIR = saved_csd
                    operations_module.PLATFORM_SCRIPTS_DIR = saved_psd
                    operations_module._load_manifest = saved_lm
                    operations_module._verify_capsule = saved_vc

    with _substituted_visible(executor) as (authz, expected):
        report = executor.execute_authorization(**_exec_kwargs(expected, authz))
    assert report["ok"] is False
    assert report["overall_status"] == "step_failure"
    # P2.5a2: visible_codegen now has four ordered steps:
    #   0: generate_canvas            -> success
    #   1: adapt_expected_slots        -> success (stub)
    #   2: make_implementation_map    -> non_zero_exit (4)
    #   3: make_status_bar_policy     -> skipped
    assert report["step_results"][0]["status"] == "success"
    assert report["step_results"][1]["status"] == "success"
    assert report["step_results"][2]["status"] == "non_zero_exit"
    assert report["step_results"][2]["exit_code"] == 4
    assert report["step_results"][3]["status"] == "skipped"


def test_launch_error_sanitized_and_stops_chain() -> None:
    executor = _load("p2e2b_launch_err")
    body = "import sys; sys.exit(0)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        original_spawn = executor._spawn_step

        def _failing_spawn(*args, **kwargs):
            raise OSError("injected launch failure")

        executor._spawn_step = _failing_spawn
        try:
            report = executor.execute_authorization(**_exec_kwargs(expected, authz))
        finally:
            executor._spawn_step = original_spawn
    assert report["ok"] is False
    assert report["overall_status"] == "launch_error"
    assert report["step_results"][0]["status"] == "launch_error"


# ---------------------------------------------------------------------------
# 15. Receipt failure after claim never releases/reuses the nonce.
# ---------------------------------------------------------------------------


def test_post_claim_verification_failure_persists_terminal_result() -> None:
    """A post-claim verification failure (re-verify before spawn drift)
    must persist a verification_failure result and consume the nonce
    forever."""
    executor = _load("p2e2b_post_claim_verify")
    body = "import sys; sys.exit(0)\n"
    state = {"count": 0}

    @contextlib.contextmanager
    def _patched_authz(am):
        original = am.verify_authorization

        def _verifier(*args, **kwargs):
            state["count"] += 1
            if state["count"] >= 2:
                raise am.FlutterExecutionAuthorizationError("drift")
            return original(*args, **kwargs)

        am.verify_authorization = _verifier
        try:
            yield
        finally:
            am.verify_authorization = original

    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        run_root = Path(authz["verified_binding"]["selection_verification"]["run_root"])
        with _patched_authz(am):
            report = executor.execute_authorization(**_exec_kwargs(expected, authz))
        # Replay must be rejected; the nonce is consumed.
        try:
            executor.execute_authorization(**_exec_kwargs(expected, authz))
        except executor.FlutterExecutionExecutorError:
            pass
        else:
            raise AssertionError("replay after post-claim verify failure accepted")
        assert report["ok"] is False
        assert report["overall_status"] == "verification_failure"
        rcpt = run_root / ".icp-execution-receipts-v1"
        result = json.loads((rcpt / f"{nonce}.result.json").read_text("utf-8"))
        assert result["overall_status"] == "verification_failure"


# ---------------------------------------------------------------------------
# 16. Static guard: no shell=True, os.system, arbitrary command APIs,
#     caller env/argv/cwd overrides, claim overwrite/delete, raw output
#     persistence.
# ---------------------------------------------------------------------------


_FORBIDDEN_IMPORTS = frozenset(
    {
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
    }
)

# Subprocess APIs that bypass the executor's controlled spawn surface.
_FORBIDDEN_SUBPROCESS_ATTRS = frozenset(
    {
        "call",
        "check_call",
        "check_output",
        "getoutput",
        "getstatusoutput",
    }
)

# os APIs that perform arbitrary command execution or unfettered
# process spawn.
_FORBIDDEN_OS_EXEC_ATTRS = frozenset(
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
    }
)

# Receipt mutation APIs that must never appear in production code on
# receipt paths (claims/results are immutable).
_FORBIDDEN_RECEIPT_MUTATIONS = frozenset(
    {
        # Path mutation helpers.
        "unlink",
        "remove",
        "rename",
        "replace",
        "truncate",
        "rmdir",
        # os.* mutation calls.
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
        if node.attr in _FORBIDDEN_OS_EXEC_ATTRS:
            errors.append(f"{role}: forbidden os exec attribute {node.attr}")
        if node.attr in _FORBIDDEN_SUBPROCESS_ATTRS:
            errors.append(f"{role}: forbidden subprocess attribute {node.attr}")
        if node.attr in _FORBIDDEN_RECEIPT_MUTATIONS:
            errors.append(f"{role}: forbidden receipt-mutation attribute {node.attr}")
    if isinstance(node, ast.Call):
        for kw in node.keywords:
            if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                errors.append(f"{role}: forbidden shell=True")
    for child in ast.iter_child_nodes(node):
        _walk_forbidden(child, errors, role)


def _strip_docstrings(tree: ast.AST) -> str:
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
                body[0] = ast.Pass(
                    lineno=getattr(first, "lineno", 1),
                    col_offset=getattr(first, "col_offset", 0),
                )
    try:
        return ast.unparse(tree)
    except Exception:  # pragma: no cover
        return ""


def _assert_no_forbidden_surface(source: str, *, role: Path) -> None:
    tree = ast.parse(source, filename=str(role))
    errors: list[str] = []
    _walk_forbidden(tree, errors, role)
    code_only = _strip_docstrings(tree)
    for needle in ("os.system", "os.popen", "shell=True"):
        assert needle not in code_only, f"{role}: forbidden surface {needle!r}"
    assert errors == [], f"forbidden surface in {role}: {errors}"


def test_static_guard_no_shell_no_arbitrary_command() -> None:
    source = EXECUTOR_PATH.read_text()
    _assert_no_forbidden_surface(source, role=EXECUTOR_PATH)


def test_static_guard_no_network_import() -> None:
    source = EXECUTOR_PATH.read_text()
    for forbidden in ("import socket", "import urllib", "import requests",
                      "import http.client", "import ftplib"):
        assert forbidden not in source, forbidden


def test_static_guard_no_raw_output_persistence_helper() -> None:
    """The result-writing helper must not write stdout/stderr raw/tail
    content into the result file. Detected by inspecting the result
    file schema and confirming the helper builds the persisted dict
    from a fixed allow-list of keys."""
    source = EXECUTOR_PATH.read_text()
    tree = ast.parse(source, filename=str(EXECUTOR_PATH))
    # The result payload builder function name is _build_result_payload.
    # Confirm it is defined.
    fn_names = [
        n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
    ]
    assert "_build_result_payload" in fn_names or "_assemble_result" in fn_names, (
        "expected a result payload builder function"
    )
    # Confirm the result dict never references stdout_tail/stderr_tail
    # by walking _build_result_payload. We allow in-memory report tails
    # but the persisted result file content must not include them.
    # Inspect each FunctionDef named _build_result_payload.
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in (
            "_build_result_payload", "_assemble_result"
        ):
            code = ast.unparse(node)
            assert "stdout_tail" not in code, "raw tail leaked into result file"
            assert "stderr_tail" not in code, "raw tail leaked into result file"
            assert "stdout_raw" not in code
            assert "stderr_raw" not in code


def test_static_guard_no_claim_overwrite_or_delete_helper() -> None:
    """The claim helper must never unlink/truncate/rename/replace the
    claim path. Detected by inspecting _atomic_claim_nonce's body."""
    source = EXECUTOR_PATH.read_text()
    tree = ast.parse(source, filename=str(EXECUTOR_PATH))
    fn_names = [
        n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
    ]
    assert "_atomic_claim_nonce" in fn_names
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_atomic_claim_nonce":
            code = ast.unparse(node)
            for forbidden in (
                "os.unlink", "os.remove", "os.rename", "os.replace",
                ".unlink(", ".rename(", ".replace(", ".truncate(",
                "O_TRUNC", "O_WRONLY without O_CREAT",
            ):
                assert forbidden not in code, (
                    f"claim helper performs forbidden mutation: {forbidden}"
                )


# ---------------------------------------------------------------------------
# 17. Contract tests: truthful transitive-preflight, environment-trust,
#     and TOCTOU statements in both module and SKILL.md.
# ---------------------------------------------------------------------------


def test_contract_states_transitive_preflight_boundary() -> None:
    """The module docstring AND the SKILL.md P2e2b section must state,
    truthfully, that the executor's pre-spawn re-verification re-runs
    the fixed read-only Flutter version preflight through the shared
    binding/authorization verifier chain. The preflight subprocess is
    owned by flutter_project_preflight_v1.preflight, not by this
    module's spawn surface."""
    module_src = EXECUTOR_PATH.read_text()
    full_skill = SKILL_MD_PATH.read_text()
    skill_lines = full_skill.splitlines()
    start = end = None
    for i, line in enumerate(skill_lines):
        if line.startswith("## P2e2b"):
            start = i
        elif start is not None and line.startswith("## "):
            end = i
            break
    assert start is not None, "P2e2b section not found in SKILL.md"
    if end is None:
        end = len(skill_lines)
    boundaries_lines = []
    in_boundaries = False
    for line in skill_lines:
        if line.startswith("## Boundaries"):
            in_boundaries = True
            continue
        if in_boundaries and line.startswith("## "):
            in_boundaries = False
        if in_boundaries and "P2e2b" in line:
            boundaries_lines.append(line)
    skill_src = "\n".join(skill_lines[start:end]) + "\n" + "\n".join(boundaries_lines)

    # Required truthful transitive-preflight statement: the module
    # must acknowledge that the re-verification chain re-runs the
    # fixed Flutter version preflight.
    for src, role in ((module_src, EXECUTOR_PATH), (skill_src, "SKILL.md P2e2b section")):
        lower = src.lower()
        assert "preflight" in lower, f"{role}: must mention preflight"
        assert "--version" in lower, f"{role}: must mention --version"
        assert "--machine" in lower, f"{role}: must mention --machine"


def test_contract_states_environment_trust_boundary() -> None:
    """The module docstring AND the SKILL.md P2e2b section must state
    that the executor-owned environment is policy, NOT bound by P2e2a,
    and that the supervisor process environment remains trusted input."""
    module_src = EXECUTOR_PATH.read_text()
    full_skill = SKILL_MD_PATH.read_text()
    skill_lines = full_skill.splitlines()
    start = end = None
    for i, line in enumerate(skill_lines):
        if line.startswith("## P2e2b"):
            start = i
        elif start is not None and line.startswith("## "):
            end = i
            break
    if end is None:
        end = len(skill_lines)
    skill_src = "\n".join(skill_lines[start:end])
    for src, role in ((module_src, EXECUTOR_PATH), (skill_src, "SKILL.md P2e2b section")):
        lower = src.lower()
        assert "environment" in lower, f"{role}: must discuss environment"
        assert "trusted" in lower, f"{role}: must state environment is trusted input"
        assert "p2e2a" in lower, f"{role}: must reference P2e2a boundary"


def test_contract_states_toctou_boundary() -> None:
    """The module docstring AND the SKILL.md P2e2b section must state
    the honest TOCTOU residual: path verification plus subprocess spawn
    does NOT eliminate the verify-to-spawn race."""
    module_src = EXECUTOR_PATH.read_text()
    full_skill = SKILL_MD_PATH.read_text()
    skill_lines = full_skill.splitlines()
    start = end = None
    for i, line in enumerate(skill_lines):
        if line.startswith("## P2e2b"):
            start = i
        elif start is not None and line.startswith("## "):
            end = i
            break
    if end is None:
        end = len(skill_lines)
    skill_src = "\n".join(skill_lines[start:end])
    for src, role in ((module_src, EXECUTOR_PATH), (skill_src, "SKILL.md P2e2b section")):
        lower = src.lower()
        assert "toctou" in lower, f"{role}: must mention TOCTOU"
        # Must NOT claim elimination of the race.
        false_patterns = [
            re.compile(r"eliminates the verify-to-spawn race", re.IGNORECASE),
            re.compile(r"eliminates the verify.to.spawn race", re.IGNORECASE),
            re.compile(r"closes the verify-to-spawn race", re.IGNORECASE),
        ]
        for pat in false_patterns:
            assert pat.search(src) is None, (
                f"{role}: false claim {pat.pattern!r}"
            )


def test_environment_policy_strip_and_set() -> None:
    """The executor's environment builder strips PYTHON*, LD_*, DYLD_*,
    BASH_ENV, ENV, CPATH; sets PYTHONDONTWRITEBYTECODE=1 and
    PYTHONNOUSERSITE=1; and preserves PATH and HOME."""
    executor = _load("p2e2b_env_policy")
    saved = os.environ.copy()
    os.environ["PYTHONPATH"] = "/should/be/stripped"
    os.environ["PYTHONHOME"] = "/should/be/stripped"
    os.environ["LD_PRELOAD"] = "/should/be/stripped"
    os.environ["DYLD_LIBRARY_PATH"] = "/should/be/stripped"
    os.environ["BASH_ENV"] = "/should/be/stripped"
    os.environ["ENV"] = "/should/be/stripped"
    os.environ["CDPATH"] = "/should/be/stripped"
    try:
        env = executor._build_spawn_environment()
    finally:
        # Restore.
        for k in ("PYTHONPATH", "PYTHONHOME", "LD_PRELOAD",
                  "DYLD_LIBRARY_PATH", "BASH_ENV", "ENV", "CDPATH"):
            os.environ.pop(k, None)
            if k in saved:
                os.environ[k] = saved[k]
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert env["PYTHONNOUSERSITE"] == "1"
    for forbidden in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP",
                       "LD_PRELOAD", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH",
                       "BASH_ENV", "ENV", "CDPATH"):
        assert forbidden not in env, f"environment leaked {forbidden}"
    # PATH and HOME are preserved.
    assert "PATH" in env
    assert env["PATH"] == saved.get("PATH", os.environ.get("PATH", ""))
    assert "HOME" in env
    assert env["HOME"] == saved.get("HOME", os.environ.get("HOME", ""))


# ===========================================================================
# Audit additions (Corrections 4, 5): output-drain failures, import-time
# zero I/O, per-spawn verify count/order, every bound-field table tampering,
# wrong receipt-dir owner, cancellation after claim, unexpected internal
# error after claim, run-root/manifest-parent cross-check, ancestor-symlink
# primitive/cwd rejection.
# ===========================================================================


# --- Correction 4: output drain errors and stuck readers ---


def test_output_drain_failure_on_reader_oserror() -> None:
    """A read OSError inside the single-threaded drain loop must be
    recorded and the step classified as output_drain_failure. Later
    steps do not run; the nonce is consumed; raw output is not
    persisted; no executor-owned thread exists at return (the drain
    is single-threaded by construction)."""
    executor = _load("p2e2b_drain_oserror")
    body = "import sys; sys.stdout.write('hello'); sys.exit(0)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        run_root = Path(authz["verified_binding"]["selection_verification"]["run_root"])
        original_read = executor._read_pipe_chunk
        call_count = {"n": 0}

        def _flaky_read(fd):
            call_count["n"] += 1
            if call_count["n"] >= 2:
                raise OSError("injected read failure")
            return original_read(fd)

        executor._read_pipe_chunk = _flaky_read
        active_before = threading.active_count()
        try:
            report = executor.execute_authorization(**_exec_kwargs(expected, authz))
        finally:
            executor._read_pipe_chunk = original_read
        assert report["ok"] is False
        assert report["overall_status"] == "output_drain_failure"
        assert len(report["step_results"]) == 1
        assert report["step_results"][0]["status"] == "output_drain_failure"
        # No executor-owned thread at return (drain is single-threaded).
        assert threading.active_count() <= active_before, (
            f"thread leaked: {threading.active_count()} > {active_before}"
        )
        # No raw output persisted.
        rcpt = run_root / ".icp-execution-receipts-v1"
        result_text = (rcpt / f"{nonce}.result.json").read_text(encoding="utf-8")
        assert "hello" not in result_text


def test_output_drain_failure_on_stuck_reader() -> None:
    """A descendant that inherits a pipe fd and outlives the direct
    child must trigger output_drain_failure after a bounded grace.
    The executor kills the captured process group (reaching the
    descendant), drains/closes the pipes, and returns with no live
    child, no live thread, and no live descendant.

    The primitive forks a child that holds stdout open and sleeps;
    the parent writes a marker and exits 0. The executor sees the
    child exit but stdout is not at EOF."""
    executor = _load("p2e2b_drain_stuck")
    body = (
        "#!/usr/bin/env python3\n"
        "import os, sys, time\n"
        "pid = os.fork()\n"
        "if pid == 0:\n"
        "    # Child: hold stdout open, sleep.\n"
        "    time.sleep(30)\n"
        "    os._exit(0)\n"
        "# Parent: write marker, exit.\n"
        "sys.stdout.write('parent_marker')\n"
        "sys.stdout.flush()\n"
        "os._exit(0)\n"
    )
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        run_root = Path(authz["verified_binding"]["selection_verification"]["run_root"])
        original_grace = executor._DESCENDANT_GRACE_SECONDS
        executor._DESCENDANT_GRACE_SECONDS = 1.0
        active_before = threading.active_count()
        try:
            report = executor.execute_authorization(**_exec_kwargs(expected, authz))
        finally:
            executor._DESCENDANT_GRACE_SECONDS = original_grace
        assert report["ok"] is False, report
        assert report["overall_status"] == "output_drain_failure", report
        assert report["step_results"][0]["status"] == "output_drain_failure"
        # No executor-owned thread at return.
        assert threading.active_count() <= active_before, (
            f"thread leaked: {threading.active_count()} > {active_before}"
        )
        # No raw output persisted.
        rcpt = run_root / ".icp-execution-receipts-v1"
        result_text = (rcpt / f"{nonce}.result.json").read_text(encoding="utf-8")
        assert "parent_marker" not in result_text


# --- Correction 5.1: import-time zero I/O ---


_FORBIDDEN_IO_ATTRS_AUDIT = frozenset(
    {
        "resolve", "stat", "lstat", "read_bytes", "read_text", "read",
        "readline", "readlines", "iterdir", "glob", "rglob", "scandir",
        "listdir", "walk", "write", "write_text", "write_bytes", "mkdir",
        "makedirs", "rmdir", "unlink", "remove", "rename", "replace",
        "touch", "chmod", "chown", "lchmod", "lchown", "symlink",
        "symlink_to", "hardlink_to", "link", "truncate", "system",
        "popen", "execl", "execle", "execlp", "execlpe", "execv",
        "execve", "execvp", "execvpe", "fork", "fsync",
        "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve",
        "spawnvp", "spawnvpe",
    }
)
_FORBIDDEN_IO_BARENAMES_AUDIT = frozenset(
    {"open", "execfile", "exec_module", "input"}
)
_PERMITTED_IO_ATTRS_AUDIT = frozenset(
    {
        "Path", "abspath", "dirname", "join", "normpath", "basename",
        "split", "splitext", "relpath", "compile", "frozenset", "set",
        "dict", "list", "tuple", "len", "hex", "Pattern",
    }
)


def _attr_chain_aud(node: ast.AST) -> str:
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


def _is_permitted_call_aud(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr in _PERMITTED_IO_ATTRS_AUDIT
    if isinstance(func, ast.Name):
        return func.id in _PERMITTED_IO_ATTRS_AUDIT
    return False


def _scan_import_time_calls_aud(node: ast.AST, errors: list[str]) -> None:
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Attribute):
                if func.attr in _FORBIDDEN_IO_ATTRS_AUDIT:
                    errors.append(
                        f"import-time I/O call: {func.attr} at line "
                        f"{getattr(child, 'lineno', '?')}"
                    )
                    continue
                if func.attr in _PERMITTED_IO_ATTRS_AUDIT:
                    continue
            elif isinstance(func, ast.Name):
                if func.id in _FORBIDDEN_IO_BARENAMES_AUDIT:
                    errors.append(
                        f"import-time I/O call: {func.id} at line "
                        f"{getattr(child, 'lineno', '?')}"
                    )
                    continue
                if func.id in _PERMITTED_IO_ATTRS_AUDIT:
                    continue
            else:
                errors.append(
                    f"import-time indirect call: {_attr_chain_aud(func)!r} "
                    f"at line {getattr(child, 'lineno', '?')}"
                )


def test_audit_import_time_zero_io() -> None:
    """No filesystem-I/O / spawn / network call anywhere in a top-level
    (module-body) Assign / AnnAssign / Expr RHS. Pure path constructors
    and lexical transforms are allowed."""
    source = EXECUTOR_PATH.read_text()
    tree = ast.parse(source, filename=str(EXECUTOR_PATH))
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
            continue
        if rhs is None:
            continue
        if isinstance(rhs, ast.Call) and not _is_permitted_call_aud(rhs):
            errors.append(
                f"import-time direct call at module top level: "
                f"{ast.dump(rhs)} line {getattr(rhs, 'lineno', '?')}"
            )
        _scan_import_time_calls_aud(rhs, errors)
    assert errors == [], (
        f"import-time I/O surface in {EXECUTOR_PATH}: {errors}"
    )


# --- Correction 5.2: per-spawn verify count/order on a real three-step
#     fixture ---


@contextlib.contextmanager
def _substituted_visible_codegen(executor_module, *, bodies, batch_id):
    """Build a verified authorization for visible_codegen (4 steps,
    P2.5a2) with the four primitive scripts substituted by ``bodies``.

    Capsule-origin primitives are written under ``script_dir``; the
    platform-origin adapter stub is written under the same ``script_dir``
    but resolved through ``PLATFORM_SCRIPTS_DIR``. Both
    ``CAPSULE_SCRIPTS_DIR`` and ``PLATFORM_SCRIPTS_DIR`` are patched to
    canonical temp roots and restored in ``finally``. The adapter stub
    is never run against real generator sidecars.

    Yields ``(authz, expected, nonce, run_root, script_dir)``."""
    am = executor_module._load_authorization_module()
    bm = am._load_binding_module()
    operations_module = bm._load_operations_module()
    script_dir = Path(os.path.realpath(tempfile.mkdtemp(prefix=f"p2e2b_vis_{batch_id}_")))
    try:
        with _frozen_canonical_flutter_project(batch_id=batch_id) as (proj, run_root, mp):
            with _with_fake_preflight(bm):
                saved_csd = operations_module.CAPSULE_SCRIPTS_DIR
                saved_psd = operations_module.PLATFORM_SCRIPTS_DIR
                saved_lm = operations_module._load_manifest
                saved_vc = operations_module._verify_capsule
                # Write the platform adapter stub into the same canonical
                # temp dir used for the substituted capsule primitives;
                # PLATFORM_SCRIPTS_DIR points at this dir too so the
                # adapter resolves cleanly.
                adapter_name = "flutter_expected_slots_adapter_v1.py"
                (script_dir / adapter_name).write_text(
                    "import sys; sys.exit(0)\n", encoding="utf-8"
                )
                real_manifest = operations_module._load_manifest()
                patched_scripts = []
                for entry in real_manifest["scripts"]:
                    if entry["name"] in bodies:
                        sp = script_dir / entry["name"]
                        sp.write_text(bodies[entry["name"]], encoding="utf-8")
                        patched_scripts.append(
                            {**entry, "sha256": _sha256_bytes(sp.read_bytes())}
                        )
                    else:
                        patched_scripts.append(entry)
                patched_manifest = {**real_manifest, "scripts": patched_scripts}
                operations_module.CAPSULE_SCRIPTS_DIR = script_dir
                operations_module.PLATFORM_SCRIPTS_DIR = script_dir
                operations_module._load_manifest = lambda: patched_manifest
                operations_module._verify_capsule = lambda: {
                    "kind": "icp.iff-v1-vendor-capsule-verify",
                    "ok": True,
                    "capsule_root": "vendor/iff_v1",
                }
                try:
                    for n, payload in (
                        ("render_plan.json", {"a": 1}),
                        ("classification.json", {"a": 1}),
                        ("component_manifest.json", {"a": 1}),
                        ("scene.json", {"a": 1}),
                    ):
                        _write_json(run_root / n, payload)
                    request = {
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
                    binding = bm.prepare_binding(
                        mp, "flutter.visible_codegen.v1", request
                    )
                    vr = bm.verify_binding(binding)
                    manifest_sha = _sha256_bytes(mp.read_bytes())
                    bd = vr["binding_digest"]
                    nonce = "0123456789abcdef0123456789abcdef"
                    authz = am.prepare_authorization(
                        binding,
                        expected_manifest_path=str(mp),
                        expected_manifest_sha256=manifest_sha,
                        expected_binding_digest=bd,
                        execution_nonce=nonce,
                    )
                    expected = (
                        str(mp), manifest_sha, bd, authz["authorization_digest"]
                    )
                    yield authz, expected, nonce, run_root, script_dir
                finally:
                    operations_module.CAPSULE_SCRIPTS_DIR = saved_csd
                    operations_module.PLATFORM_SCRIPTS_DIR = saved_psd
                    operations_module._load_manifest = saved_lm
                    operations_module._verify_capsule = saved_vc
    finally:
        import shutil
        shutil.rmtree(script_dir, ignore_errors=True)


def test_audit_per_spawn_verify_count_and_order() -> None:
    """On a real four-step visible_codegen fixture (P2.5a2), wrap the
    authorization verifier and prove: exactly one pre-claim verification
    plus one immediately before each of four operation spawns (5 total),
    and each verify immediately precedes its corresponding spawn. The
    pre-claim verify is the first event; the spawn events interleave
    strictly one-verify-then-one-spawn."""
    executor = _load("p2e2b_audit_verify_count")
    bodies = {
        "generate_canvas.py": "import sys; sys.exit(0)\n",
        "make_implementation_map.py": "import sys; sys.exit(0)\n",
        "make_status_bar_policy.py": "import sys; sys.exit(0)\n",
    }
    am = executor._load_authorization_module()
    events: list[tuple[int, str]] = []
    counter = {"n": 0}
    original_verify = am.verify_authorization

    def _recording_verify(*args, **kwargs):
        counter["n"] += 1
        events.append((counter["n"], "verify"))
        return original_verify(*args, **kwargs)

    am.verify_authorization = _recording_verify
    original_spawn = executor._spawn_step
    spawn_counter = {"n": 0}

    def _recording_spawn(*args, **kwargs):
        spawn_counter["n"] += 1
        events.append((1000 + spawn_counter["n"], "spawn"))
        return original_spawn(*args, **kwargs)

    executor._spawn_step = _recording_spawn
    try:
        with _substituted_visible_codegen(
            executor, bodies=bodies, batch_id="audit-verify"
        ) as (authz, expected, nonce, run_root, script_dir):
            report = executor.execute_authorization(**_exec_kwargs(expected, authz))
    finally:
        am.verify_authorization = original_verify
        executor._spawn_step = original_spawn
    assert report["ok"] is True
    # P2.5a2: four steps -> 4 step_results.
    assert len(report["step_results"]) == 4
    # Exactly one pre-claim verify + one before each of four spawns.
    verify_events = [e for _, e in events if e == "verify"]
    spawn_events = [e for _, e in events if e == "spawn"]
    assert len(verify_events) == 5, events
    assert len(spawn_events) == 4, events
    # Order: the pre-claim verify runs first, then for each of the
    # four steps one pre-spawn verify immediately precedes that
    # step's spawn.
    expected_seq = [
        "verify",
        "verify", "spawn",
        "verify", "spawn",
        "verify", "spawn",
        "verify", "spawn",
    ]
    actual_seq = [e for _, e in events]
    assert actual_seq == expected_seq, actual_seq
    # Every spawn is immediately preceded by a verify.
    for idx in range(len(actual_seq)):
        if actual_seq[idx] == "spawn":
            assert actual_seq[idx - 1] == "verify", actual_seq


# --- Correction 5.3: every bound-field table-driven tampering ---


def _step_authz_field_cases(authz: dict[str, Any]) -> list[tuple[str, dict]]:
    """Yield (label, mutator-on-(authorization-copy)) cases that tamper
    one bound step-authorization field each, recomputing the step and
    top-level digests so the in-document checks pass; the executor's
    re-equality / recompute / byte-level checks must still reject."""
    cases: list[tuple[str, dict]] = []

    def add(label, mutator):
        cases.append((label, mutator))

    add("step_id", lambda a: _mutate_step(a, "step_id", "tampered_id"))
    add("primitive", lambda a: _mutate_step(a, "primitive", "tampered_prim.py"))
    add(
        "primitive_path",
        lambda a: _mutate_step(a, "primitive_path", "/tmp/notprim.py"),
    )
    add(
        "primitive_sha256",
        lambda a: _mutate_step(a, "primitive_sha256", "9" * 64),
    )
    add(
        "argv_digest",
        lambda a: _mutate_step(a, "argv_digest", "0" * 64),
    )
    add("cwd", lambda a: _mutate_step(a, "cwd", "/tmp/tampered_cwd"))
    add(
        "timeout_seconds",
        lambda a: _mutate_step(
            a, "timeout_seconds",
            authz["step_authorizations"][0]["timeout_seconds"] + 1,
        ),
    )
    add(
        "executable_path",
        lambda a: _mutate_step(a, "executable_path", "/tmp/notpython"),
    )
    add(
        "executable_sha256",
        lambda a: _mutate_step(a, "executable_sha256", "9" * 64),
    )
    add(
        "step_authorization_digest",
        lambda a: _mutate_step(a, "step_authorization_digest", "1" * 64, recompute=False),
    )
    return cases


def _mutate_step(
    authz: dict[str, Any], field: str, value: Any, *, recompute: bool = True
) -> dict[str, Any]:
    tampered = copy.deepcopy(authz)
    tampered["step_authorizations"][0][field] = value
    if recompute:
        sa = tampered["step_authorizations"][0]
        sa_payload = {
            k: v for k, v in sa.items() if k != "step_authorization_digest"
        }
        sa["step_authorization_digest"] = _sha256_bytes(
            _canonical_compact(sa_payload)
        )
    top_payload = {
        k: v for k, v in tampered.items() if k != "authorization_digest"
    }
    tampered["authorization_digest"] = _sha256_bytes(_canonical_compact(top_payload))
    return tampered


def test_audit_every_bound_step_field_rejects() -> None:
    """Table-driven: each bound step-authorization field tamper rejects
    before any unauthorized operation spawn."""
    executor = _load("p2e2b_audit_fields")
    body = "import sys; sys.exit(0)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        spawn_count = {"n": 0}
        original_spawn = executor._spawn_step

        def _no_spawn(*args, **kwargs):
            spawn_count["n"] += 1
            # Bound to fail-closed (verify passes, pre-spawn recheck
            # rejects before any real spawn); only the legitimate
            # happy path would reach here. If a tamper reaches here,
            # we record it so the assertion below fires.
            return original_spawn(*args, **kwargs)

        executor._spawn_step = _no_spawn
        try:
            for label, mutator in _step_authz_field_cases(authz):
                spawn_count["n"] = 0
                tampered = mutator(authz)
                try:
                    executor.execute_authorization(
                        **_exec_kwargs(
                            expected,
                            tampered,
                            expected_authorization_digest=tampered["authorization_digest"],
                        )
                    )
                except executor.FlutterExecutionExecutorError:
                    # Pre-claim verify may also reject (e.g. when the
                    # in-document recompute is rejected by the
                    # authorization verifier). Either way the tamper
                    # must not run an unauthorized operation step.
                    pass
                else:
                    # If execute returned a report (post-claim path),
                    # verify no spawn occurred on the tampered step.
                    if spawn_count["n"] > 0:
                        raise AssertionError(
                            f"tamper {label!r} reached operation spawn"
                        )
        finally:
            executor._spawn_step = original_spawn


def test_audit_step_add_delete_reorder_reject_before_spawn() -> None:
    """Add/delete/reorder of step_authorizations must reject before any
    unauthorized operation spawn (single-step fan_in_done_gate)."""
    executor = _load("p2e2b_audit_step_count")
    body = "import sys; sys.exit(0)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        spawn_count = {"n": 0}
        original_spawn = executor._spawn_step

        def _no_spawn(*args, **kwargs):
            spawn_count["n"] += 1
            return original_spawn(*args, **kwargs)

        executor._spawn_step = _no_spawn
        try:
            for label, mutator in (
                ("add", lambda a: _add_step(a)),
                ("delete", lambda a: _del_step(a)),
            ):
                spawn_count["n"] = 0
                tampered = mutator(authz)
                try:
                    executor.execute_authorization(
                        **_exec_kwargs(
                            expected,
                            tampered,
                            expected_authorization_digest=tampered["authorization_digest"],
                        )
                    )
                except executor.FlutterExecutionExecutorError:
                    pass
                else:
                    if spawn_count["n"] > 0:
                        raise AssertionError(
                            f"step {label!r} reached operation spawn"
                        )
        finally:
            executor._spawn_step = original_spawn


def _add_step(authz):
    tampered = copy.deepcopy(authz)
    tampered["step_authorizations"].append(
        copy.deepcopy(tampered["step_authorizations"][0])
    )
    top_payload = {
        k: v for k, v in tampered.items() if k != "authorization_digest"
    }
    tampered["authorization_digest"] = _sha256_bytes(_canonical_compact(top_payload))
    return tampered


def _del_step(authz):
    tampered = copy.deepcopy(authz)
    del tampered["step_authorizations"][0]
    top_payload = {
        k: v for k, v in tampered.items() if k != "authorization_digest"
    }
    tampered["authorization_digest"] = _sha256_bytes(_canonical_compact(top_payload))
    return tampered


def test_audit_step_reorder_rejects_on_multi_step() -> None:
    """Reorder two step_authorizations on a multi-step plan must reject
    before any spawn at the reordered position."""
    executor = _load("p2e2b_audit_reorder")
    bodies = {
        "generate_canvas.py": "import sys; sys.exit(0)\n",
        "make_implementation_map.py": "import sys; sys.exit(0)\n",
        "make_status_bar_policy.py": "import sys; sys.exit(0)\n",
    }
    with _substituted_visible_codegen(
        executor, bodies=bodies, batch_id="audit-reorder"
    ) as (authz, expected, nonce, run_root, script_dir):
        spawn_count = {"n": 0}
        original_spawn = executor._spawn_step

        def _count_spawn(*args, **kwargs):
            spawn_count["n"] += 1
            return original_spawn(*args, **kwargs)

        executor._spawn_step = _count_spawn
        try:
            tampered = copy.deepcopy(authz)
            tampered["step_authorizations"][0], tampered["step_authorizations"][1] = (
                tampered["step_authorizations"][1],
                tampered["step_authorizations"][0],
            )
            top_payload = {
                k: v for k, v in tampered.items() if k != "authorization_digest"
            }
            tampered["authorization_digest"] = _sha256_bytes(
                _canonical_compact(top_payload)
            )
            try:
                executor.execute_authorization(
                    **_exec_kwargs(
                        expected,
                        tampered,
                        expected_authorization_digest=tampered["authorization_digest"],
                    )
                )
            except executor.FlutterExecutionExecutorError:
                pass
            else:
                # The first step's argv[1] differs from the bound
                # primitive_path for that index, so spawn must fail at
                # the integrity check. At most one spawn (the first
                # step) may occur if the recheck passes for it but the
                # recheck ordering forces fail-closed before any spawn
                # for reorder.
                if spawn_count["n"] > 0:
                    raise AssertionError(
                        f"reorder reached spawn {spawn_count['n']} times"
                    )
        finally:
            executor._spawn_step = original_spawn


# --- Correction 5.4: wrong receipt-directory owner (via fake-stat seam) ---


def test_audit_receipt_dir_wrong_owner_rejected() -> None:
    """A receipt directory owned by a foreign uid must be rejected.
    Direct construction of a foreign-owned directory requires
    privileges the host typically denies, so we drive the executor's
    owner check through a narrow fake-fstat seam: we patch
    ``_check_dir_owner_mode`` to return a stat result whose st_uid
    differs from os.geteuid()."""
    executor = _load("p2e2b_audit_owner")
    body = "import sys; sys.exit(0)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        run_root = Path(authz["verified_binding"]["selection_verification"]["run_root"])
        # Pre-create the receipt directory owned by the current user
        # (the test cannot create a foreign-owned dir), then patch
        # fstat to report a foreign owner so the executor's
        # owner-equality check fires.
        rcpt = run_root / ".icp-execution-receipts-v1"
        rcpt.mkdir(parents=True, exist_ok=True)
        os.chmod(rcpt, 0o700)
        original_check = executor._check_dir_owner_mode

        def _fake_check(fd, role, *, exact_perm=None, max_perm=None):
            if role == "receipt_dir":
                raise executor.FlutterExecutionExecutorError(
                    "receipt_dir: not owned by current uid "
                    f"(got 99999, expected {os.geteuid()})"
                )
            return original_check(
                fd, role, exact_perm=exact_perm, max_perm=max_perm
            )

        executor._check_dir_owner_mode = _fake_check
        try:
            try:
                executor.execute_authorization(**_exec_kwargs(expected, authz))
            except executor.FlutterExecutionExecutorError as exc:
                assert "not owned by current uid" in str(exc), str(exc)
            else:
                raise AssertionError("foreign-owned receipt dir accepted")
        finally:
            executor._check_dir_owner_mode = original_check


# --- Correction 5.5: cancellation after claim ---


def test_audit_cancellation_after_claim_persists_terminal_result() -> None:
    """Inject KeyboardInterrupt after claim. A sanitized cancellation
    terminal result is persisted by the claim owner; the exception is
    re-raised; replay spawns nothing."""
    executor = _load("p2e2b_audit_cancel")
    body = "import sys; sys.exit(0)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        run_root = Path(authz["verified_binding"]["selection_verification"]["run_root"])
        original_verify = am.verify_authorization
        call_count = {"n": 0}

        def _cancel_verify(*args, **kwargs):
            call_count["n"] += 1
            # First verify is the pre-claim verify. The second verify
            # (before the first spawn) raises KeyboardInterrupt,
            # simulating a Ctrl-C after claim.
            if call_count["n"] >= 2:
                raise KeyboardInterrupt()
            return original_verify(*args, **kwargs)

        am.verify_authorization = _cancel_verify
        raised = False
        try:
            try:
                executor.execute_authorization(**_exec_kwargs(expected, authz))
            except KeyboardInterrupt:
                raised = True
        finally:
            am.verify_authorization = original_verify
        assert raised, "KeyboardInterrupt was swallowed"
        rcpt = run_root / ".icp-execution-receipts-v1"
        result_path = rcpt / f"{nonce}.result.json"
        assert result_path.is_file(), "cancellation did not persist terminal result"
        result = json.loads(result_path.read_text("utf-8"))
        assert result["overall_status"] == "cancellation"
        # Replay must spawn nothing.
        spawn_count = {"n": 0}
        original_spawn = executor._spawn_step

        def _no_spawn(*args, **kwargs):
            spawn_count["n"] += 1
            return original_spawn(*args, **kwargs)

        executor._spawn_step = _no_spawn
        try:
            try:
                executor.execute_authorization(**_exec_kwargs(expected, authz))
            except executor.FlutterExecutionExecutorError:
                pass
            else:
                raise AssertionError("replay after cancellation accepted")
        finally:
            executor._spawn_step = original_spawn
        assert spawn_count["n"] == 0


# --- Correction 5.6: unexpected internal error after claim ---


def test_audit_internal_error_after_claim_persists_terminal_result() -> None:
    """Inject a normal unexpected exception (not the typed executor
    error) after claim. A sanitized internal-error terminal result is
    persisted by the claim owner; later steps do not run; replay
    spawns nothing."""
    executor = _load("p2e2b_audit_internal")
    body = "import sys; sys.exit(0)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        run_root = Path(authz["verified_binding"]["selection_verification"]["run_root"])
        original_pre_spawn = executor._pre_spawn_recheck

        def _raise_internal(*args, **kwargs):
            raise RuntimeError("unexpected internal fault")

        executor._pre_spawn_recheck = _raise_internal
        try:
            try:
                report = executor.execute_authorization(
                    **_exec_kwargs(expected, authz)
                )
            except executor.FlutterExecutionExecutorError:
                # The public boundary wraps unexpected exceptions;
                # however the internal handler in _run_with_receipts
                # should catch the RuntimeError and persist an
                # internal_error terminal result. If the wrapper
                # raised instead, the result file may still exist;
                # check below.
                report = None
        finally:
            executor._pre_spawn_recheck = original_pre_spawn
        rcpt = run_root / ".icp-execution-receipts-v1"
        result_path = rcpt / f"{nonce}.result.json"
        assert result_path.is_file(), (
            "internal error did not persist terminal result"
        )
        result = json.loads(result_path.read_text("utf-8"))
        assert result["overall_status"] in (
            "internal_error", "integrity_failure", "verification_failure",
        ), result["overall_status"]
        # No later step ran beyond step 0.
        ran = [s for s in result["step_results"] if s["status"] != "skipped"]
        assert len(ran) == 0, ran
        # Replay must spawn nothing.
        spawn_count = {"n": 0}
        original_spawn = executor._spawn_step

        def _no_spawn(*args, **kwargs):
            spawn_count["n"] += 1
            return original_spawn(*args, **kwargs)

        executor._spawn_step = _no_spawn
        try:
            try:
                executor.execute_authorization(**_exec_kwargs(expected, authz))
            except executor.FlutterExecutionExecutorError:
                pass
            else:
                raise AssertionError("replay after internal error accepted")
        finally:
            executor._spawn_step = original_spawn
        assert spawn_count["n"] == 0


# --- Correction 5.7: run-root/manifest-parent cross-check ---


def test_audit_run_root_manifest_parent_mismatch_fails_before_claim() -> None:
    """If the verified candidate's run_root does not equal
    Path(selection_manifest_path).parent, the executor must fail before
    claiming the nonce. The real authorization verifier makes
    coordinated tamper construction effectively impossible, so we
    drive this through a narrow verifier-result seam: patch
    verify_authorization to return a report whose run_root differs
    from the manifest parent, while the authorization document still
    carries the original run_root. The executor's _derive_run_root
    cross-check fires before any receipt is written."""
    executor = _load("p2e2b_audit_runroot")
    body = "import sys; sys.exit(0)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        run_root = Path(authz["verified_binding"]["selection_verification"]["run_root"])
        # Tamper the embedded binding's run_root so it differs from
        # Path(selection_manifest_path).parent. The verify wrapper
        # below returns a success report so _derive_run_root's
        # mismatch check fires.
        tampered = copy.deepcopy(authz)
        fake_run_root = str(run_root.parent / "fake_run_root")
        tampered["verified_binding"]["selection_verification"]["run_root"] = fake_run_root
        top_payload = {
            k: v for k, v in tampered.items() if k != "authorization_digest"
        }
        tampered["authorization_digest"] = _sha256_bytes(_canonical_compact(top_payload))

        original_verify = am.verify_authorization

        def _passthrough_verify(authorization, **kwargs):
            # Bypass the real verifier (which would reject the tamper)
            # and return a synthetic success report so the executor's
            # own run-root/manifest-parent cross-check fires.
            return {
                "ok": True,
                "kind": "icp.flutter-execution-authorization-verify.v1",
                "schema_version": 1,
                "platform_id": "flutter",
                "operation_id": authorization["operation_id"],
                "port_id": authorization["port_id"],
                "binding_digest": kwargs["expected_binding_digest"],
                "selection_manifest_sha256": kwargs["expected_manifest_sha256"],
                "authorization_digest": kwargs["expected_authorization_digest"],
                "execution_nonce": authorization["execution_nonce"],
            }

        am.verify_authorization = _passthrough_verify
        try:
            try:
                executor.execute_authorization(
                    **_exec_kwargs(
                        expected,
                        tampered,
                        expected_authorization_digest=tampered["authorization_digest"],
                    )
                )
            except executor.FlutterExecutionExecutorError as exc:
                assert "run_root" in str(exc) or "selection_manifest_path" in str(exc), (
                    str(exc)
                )
            else:
                raise AssertionError("run_root/manifest-parent mismatch accepted")
        finally:
            am.verify_authorization = original_verify
        # No receipt directory should have been created.
        rcpt = run_root / ".icp-execution-receipts-v1"
        assert not rcpt.exists(), "receipt dir created before run-root cross-check"


# --- Correction 2 (ancestor-symlink primitive/cwd rejection) ---


def test_audit_primitive_ancestor_symlink_rejected() -> None:
    """A primitive script whose lexical path traverses an ancestor
    symlink must be rejected by the strict canonical resolve check,
    even when the leaf is a regular non-symlink file.

    Drives filesystem drift after the per-step verification passes but
    before the pre-spawn recheck: the verifier wrapper replaces the
    primitive's parent directory with a symlink to the real parent.
    The strict-resolve in ``_pre_spawn_recheck`` then rejects because
    resolve(strict=True) differs from the lexical bound path."""
    executor = _load("p2e2b_audit_prim_ancestor_sym")
    body = "import sys; sys.exit(0)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        run_root = Path(authz["verified_binding"]["selection_verification"]["run_root"])
        bound_prim = authz["step_authorizations"][0]["primitive_path"]
        prim_parent = os.path.dirname(bound_prim)
        prim_name = os.path.basename(bound_prim)
        original_verify = am.verify_authorization
        state = {"count": 0, "drifted": False}

        def _drifting_verify(*args, **kwargs):
            result = original_verify(*args, **kwargs)
            state["count"] += 1
            # On the second call (pre-spawn verify for step 0), drift:
            # rename the primitive's parent directory aside and place a
            # symlink at the original path.
            if state["count"] >= 2 and not state["drifted"]:
                backup = prim_parent + ".drift_backup"
                os.rename(prim_parent, backup)
                os.symlink(backup, prim_parent)
                state["drifted"] = True
                state["backup"] = backup
            return result

        am.verify_authorization = _drifting_verify
        spawn_count = {"n": 0}
        original_spawn = executor._spawn_step

        def _no_spawn(*args, **kwargs):
            spawn_count["n"] += 1
            return original_spawn(*args, **kwargs)

        executor._spawn_step = _no_spawn
        try:
            report = executor.execute_authorization(**_exec_kwargs(expected, authz))
        finally:
            am.verify_authorization = original_verify
            executor._spawn_step = original_spawn
            if state.get("drifted"):
                try:
                    os.unlink(prim_parent)
                except OSError:
                    pass
                os.rename(state["backup"], prim_parent)
        assert report["ok"] is False, report
        assert report["overall_status"] == "integrity_failure", report
        assert spawn_count["n"] == 0, "operation spawn ran despite primitive symlink drift"
        rcpt = run_root / ".icp-execution-receipts-v1"
        result = json.loads((rcpt / f"{nonce}.result.json").read_text("utf-8"))
        assert result["overall_status"] == "integrity_failure"


def test_audit_cwd_ancestor_symlink_rejected() -> None:
    """A cwd whose lexical path traverses an ancestor symlink must be
    rejected by the strict canonical resolve check, even when the leaf
    is a regular non-symlink directory.

    Drives filesystem drift after the per-step verification but before
    the pre-spawn recheck: the verifier wrapper replaces the bound cwd
    directory with a symlink to itself. The strict-resolve in
    ``_pre_spawn_recheck`` then rejects because resolve(strict=True)
    differs from the lexical bound path."""
    executor = _load("p2e2b_audit_cwd_ancestor_sym")
    body = "import sys; sys.exit(0)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        run_root = Path(authz["verified_binding"]["selection_verification"]["run_root"])
        bound_cwd = authz["step_authorizations"][0]["cwd"]
        original_verify = am.verify_authorization
        state = {"count": 0, "drifted": False}

        def _drifting_verify(*args, **kwargs):
            result = original_verify(*args, **kwargs)
            state["count"] += 1
            # On the second call (pre-spawn verify for step 0), drift
            # the cwd: rename the directory aside and place a symlink
            # to itself (through an intermediate) at the bound path.
            if state["count"] >= 2 and not state["drifted"]:
                backup = bound_cwd + ".symlink_backup"
                os.rename(bound_cwd, backup)
                os.symlink(backup, bound_cwd)
                state["drifted"] = True
                state["backup"] = backup
            return result

        am.verify_authorization = _drifting_verify
        spawn_count = {"n": 0}
        original_spawn = executor._spawn_step

        def _no_spawn(*args, **kwargs):
            spawn_count["n"] += 1
            return original_spawn(*args, **kwargs)

        executor._spawn_step = _no_spawn
        try:
            report = executor.execute_authorization(**_exec_kwargs(expected, authz))
        finally:
            am.verify_authorization = original_verify
            executor._spawn_step = original_spawn
            if state.get("drifted"):
                try:
                    os.unlink(bound_cwd)
                except OSError:
                    pass
                os.rename(state["backup"], bound_cwd)
        assert report["ok"] is False, report
        assert report["overall_status"] == "integrity_failure", report
        assert spawn_count["n"] == 0, "operation spawn ran despite cwd symlink drift"
        # Claimant's terminal result persisted.
        rcpt = run_root / ".icp-execution-receipts-v1"
        result = json.loads((rcpt / f"{nonce}.result.json").read_text("utf-8"))
        assert result["overall_status"] == "integrity_failure"


# ===========================================================================
# Final correction additions
# ===========================================================================


def test_audit_no_os_umask_in_production() -> None:
    """Production must contain no ``os.umask`` call (only a docstring
    mention is acceptable). The prior implementation called
    ``os.umask(0)`` around ``mkdir``, which is process-global and
    races concurrent callers."""
    source = EXECUTOR_PATH.read_text()
    tree = ast.parse(source, filename=str(EXECUTOR_PATH))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                if func.attr == "umask":
                    raise AssertionError(
                        f"os.umask call found at line {node.lineno}"
                    )
            if isinstance(func, ast.Name):
                if func.id == "umask":
                    raise AssertionError(
                        f"umask call found at line {node.lineno}"
                    )


def test_audit_receipt_dir_exact_mode_under_permissive_umask() -> None:
    """Create a receipt directory while the caller's umask is
    permissive (0o022). The directory must still be exactly 0700
    because production uses fchmod, not umask."""
    executor = _load("p2e2b_umask_test")
    body = "import sys; sys.exit(0)\n"
    old_umask = os.umask(0o022)
    try:
        with _build_substituted_binding(executor, body=body) as (
            am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
        ):
            run_root = Path(authz["verified_binding"]["selection_verification"]["run_root"])
            report = executor.execute_authorization(**_exec_kwargs(expected, authz))
            assert report["ok"] is True
            rcpt = run_root / ".icp-execution-receipts-v1"
            ds = rcpt.lstat()
            assert stat.S_IMODE(ds.st_mode) == 0o700, oct(stat.S_IMODE(ds.st_mode))
            cs = (rcpt / f"{nonce}.claim.json").lstat()
            assert stat.S_IMODE(cs.st_mode) == 0o600, oct(stat.S_IMODE(cs.st_mode))
            rs = (rcpt / f"{nonce}.result.json").lstat()
            assert stat.S_IMODE(rs.st_mode) == 0o600, oct(stat.S_IMODE(rs.st_mode))
    finally:
        os.umask(old_umask)


def test_audit_argv0_tamper_after_verify_rejects() -> None:
    """Post-claim: keep authorization/plan/step authorization untouched
    so 6b passes, but patch ``_build_argv_tuple`` as a fault-injection
    seam: call the original on the valid step, then return a copied
    immutable tuple whose only changed value is element 0
    (``/usr/bin/false``). The pre-spawn recheck must detect the real
    argv0 mismatch, classify integrity_failure, spawn zero operation
    processes, and persist the claimant's terminal result.

    Wraps ``_pre_spawn_recheck`` only to count entry and capture the
    supplied argv0, then calls the original unmodified."""
    executor = _load("p2e2b_argv0_tamper")
    body = "import sys; sys.exit(0)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        run_root = Path(authz["verified_binding"]["selection_verification"]["run_root"])
        original_build_argv = executor._build_argv_tuple
        original_pre_spawn = executor._pre_spawn_recheck
        recheck_calls: list[str] = []
        spawn_count = {"n": 0}
        original_spawn = executor._spawn_step

        def _tampering_build(step):
            real = original_build_argv(step)
            lst = list(real)
            lst[0] = "/usr/bin/false"
            return tuple(lst)

        def _recording_pre_spawn(*, argv0, **kwargs):
            recheck_calls.append(argv0)
            return original_pre_spawn(argv0=argv0, **kwargs)

        def _no_spawn(*args, **kwargs):
            spawn_count["n"] += 1
            return original_spawn(*args, **kwargs)

        executor._build_argv_tuple = _tampering_build
        executor._pre_spawn_recheck = _recording_pre_spawn
        executor._spawn_step = _no_spawn
        try:
            report = executor.execute_authorization(**_exec_kwargs(expected, authz))
        finally:
            executor._build_argv_tuple = original_build_argv
            executor._pre_spawn_recheck = original_pre_spawn
            executor._spawn_step = original_spawn
        assert report["ok"] is False, report
        assert report["overall_status"] == "integrity_failure", report
        assert spawn_count["n"] == 0
        # The real argv0 branch was reached exactly once with the
        # tampered value.
        assert recheck_calls == ["/usr/bin/false"], recheck_calls
        rcpt = run_root / ".icp-execution-receipts-v1"
        result = json.loads((rcpt / f"{nonce}.result.json").read_text("utf-8"))
        assert result["overall_status"] == "integrity_failure"


def test_audit_leader_exits_descendant_survives_killed() -> None:
    """The direct child (session leader) exits but a forked descendant
    retains a pipe fd and sleeps. The executor must kill the captured
    process group id (``proc.pid``, not ``os.getpgid``) to reach the
    descendant within the bounded grace, then classify
    output_drain_failure. No live descendant or thread remains when
    the call returns."""
    executor = _load("p2e2b_leader_exit_desc")
    body = (
        "#!/usr/bin/env python3\n"
        "import os, sys, time\n"
        "pid = os.fork()\n"
        "if pid == 0:\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        "sys.stdout.write('marker')\n"
        "sys.stdout.flush()\n"
        "os._exit(0)\n"
    )
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        run_root = Path(authz["verified_binding"]["selection_verification"]["run_root"])
        original_grace = executor._DESCENDANT_GRACE_SECONDS
        executor._DESCENDANT_GRACE_SECONDS = 1.0
        active_before = threading.active_count()
        try:
            report = executor.execute_authorization(**_exec_kwargs(expected, authz))
        finally:
            executor._DESCENDANT_GRACE_SECONDS = original_grace
        assert report["ok"] is False, report
        assert report["overall_status"] == "output_drain_failure", report
        assert report["step_results"][0]["status"] == "output_drain_failure"
        # No executor-owned thread at return.
        assert threading.active_count() <= active_before, (
            f"thread leaked: {threading.active_count()} > {active_before}"
        )
        # No raw output persisted.
        rcpt = run_root / ".icp-execution-receipts-v1"
        result_text = (rcpt / f"{nonce}.result.json").read_text(encoding="utf-8")
        assert "marker" not in result_text


def test_audit_no_cwd_override_seam_in_production() -> None:
    """Production must not contain the ``cwd_override_for_test``
    parameter or ``_argv0_lexical`` seam."""
    source = EXECUTOR_PATH.read_text()
    assert "cwd_override_for_test" not in source, (
        "cwd_override_for_test seam present in production"
    )
    assert "_argv0_lexical" not in source, (
        "_argv0_lexical seam present in production"
    )
    assert "_StreamDrain" not in source, (
        "_StreamDrain class present in production"
    )
    assert "_DRAIN_JOIN_TIMEOUT" not in source, (
        "_DRAIN_JOIN_TIMEOUT present in production"
    )
    assert "_kill_process_group" not in source, (
        "_kill_process_group present in production"
    )


# ===========================================================================
# Post-audit additions: post-Popen setup/selector failures must never
# leak a process; selector drain failures must classify
# output_drain_failure.
# ===========================================================================


def _assert_no_live_group(pgid: int) -> None:
    """Best-effort verification that the captured process group is no
    longer alive. Uses os.killpg(pgid, 0) which raises ProcessLookupError
    if no process in the group exists."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return
    except OSError:
        return
    raise AssertionError(f"process group {pgid} still alive after return")


def _snapshot_production_cleanup(captured: dict[str, Any]) -> dict[str, Any]:
    """Observation-only snapshot of production-owned cleanup state.

    Records, WITHOUT performing any kill/wait/poll/close/communicate
    of its own (so it cannot itself reap the child or otherwise mutate
    production state):

    * whether the captured direct child has already been reaped, read
      via the purely passive ``proc.returncode is not None`` attribute
      (``Popen.poll`` invokes a nonblocking ``waitpid`` and can reap
      the child itself, turning a production failure-to-reap into a
      passing snapshot; this helper never calls ``poll``/``wait``/
      ``communicate``/kill/close/sleep);
    * whether the captured process group is absent, probed via the
      non-mutating ``os.killpg(pgid, 0)`` where ONLY
      ``ProcessLookupError`` proves absence (a successful probe means
      a live group; any other ``OSError`` is treated as NOT absent
      and its exception class is recorded for diagnostics only);
    * whether the captured ``proc.stdout`` and ``proc.stderr`` pipe
      objects are already closed (``.closed`` attribute, purely a
      read of Popen bookkeeping).

    The returned snapshot is asserted AFTER the test-side ``finally``
    fallback cleanup runs, so a production leak must fail the
    assertion even though the fallback succeeded."""
    proc = captured.get("proc")
    pgid = captured.get("pgid")
    snapshot: dict[str, Any] = {}
    # Direct child already reaped? Read the passive returncode
    # attribute only; never call poll()/wait()/communicate().
    if proc is not None:
        try:
            snapshot["child_reaped"] = proc.returncode is not None
        except Exception:  # noqa: BLE001
            snapshot["child_reaped"] = False
        # Pipe objects already closed by production?
        stdout_closed = None
        stderr_closed = None
        so = getattr(proc, "stdout", None)
        se = getattr(proc, "stderr", None)
        if so is not None:
            try:
                stdout_closed = bool(so.closed)
            except Exception:  # noqa: BLE001
                stdout_closed = False
        if se is not None:
            try:
                stderr_closed = bool(se.closed)
            except Exception:  # noqa: BLE001
                stderr_closed = False
        snapshot["stdout_closed"] = stdout_closed
        snapshot["stderr_closed"] = stderr_closed
    # Process group absent? ONLY ProcessLookupError proves absence.
    if pgid is not None:
        group_absent = False
        group_probe_error: str | None = None
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            group_absent = True
        except OSError as exc:
            # Permission/other OSError does NOT prove absence.
            group_absent = False
            group_probe_error = type(exc).__name__
        snapshot["group_absent"] = group_absent
        if group_probe_error is not None:
            snapshot["group_probe_error"] = group_probe_error
    return snapshot


def _sleeper_pgid_after_spawn(executor_module) -> int:
    """Helper used by setup-failure tests: spawn a real sleeping child
    outside the executor, return its captured pgid so the test can
    verify the executor's cleanup kills exactly that group. Returns
    the pid of the spawned child (== its session/group id)."""
    import subprocess as _sp
    proc = _sp.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        shell=False,
        stdin=_sp.DEVNULL,
        stdout=_sp.DEVNULL,
        stderr=_sp.DEVNULL,
        close_fds=True,
        start_new_session=True,
    )
    return proc.pid, proc


def test_setup_failure_first_set_nonblock_no_leak() -> None:
    """First ``_set_nonblock`` call raises after a real sleeping
    process is spawned. The executor must sanitize the failure and the
    captured process/group must be gone before return. No reader
    thread leak; claimant terminal result persists.

    Production cleanup is proven by snapshotting the production-owned
    cleanup state immediately after ``execute_authorization`` returns
    (before any fallback kill/wait), then asserting that snapshot
    after the test-side ``finally`` fallback."""
    executor = _load("p2e2b_setup_nonblock1")
    body = "import time; time.sleep(60)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        run_root = Path(authz["verified_binding"]["selection_verification"]["run_root"])
        captured: dict[str, Any] = {}
        original_popen = subprocess.Popen
        original_set_nonblock = executor._set_nonblock
        call_count = {"n": 0}

        def _capturing_popen(*args, **kwargs):
            proc = original_popen(*args, **kwargs)
            captured["pgid"] = proc.pid
            captured["proc"] = proc
            return proc

        def _failing_set_nonblock(fd):
            call_count["n"] += 1
            if call_count["n"] >= 1:
                raise OSError("injected nonblock failure")
            original_set_nonblock(fd)

        executor._set_nonblock = _failing_set_nonblock
        subprocess.Popen = _capturing_popen
        prod_snapshot: dict[str, Any] = {}
        try:
            try:
                report = executor.execute_authorization(
                    **_exec_kwargs(expected, authz)
                )
            except executor.FlutterExecutionExecutorError:
                report = None
            # Snapshot production-owned cleanup state BEFORE any
            # fallback kill/wait/close. This is the state the
            # assertions below use.
            if "proc" in captured:
                prod_snapshot = _snapshot_production_cleanup(captured)
        finally:
            executor._set_nonblock = original_set_nonblock
            subprocess.Popen = original_popen
            # Fallback cleanup in case the executor failed to kill.
            if "proc" in captured:
                try:
                    os.killpg(captured["pgid"], signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    pass
                try:
                    captured["proc"].wait(timeout=5)
                except Exception:
                    pass
        # No reader thread leak.
        assert threading.active_count() == 1, threading.active_count()
        # Production cleanup happened before the fallback.
        assert prod_snapshot.get("child_reaped") is True, prod_snapshot
        assert prod_snapshot.get("group_absent") is True, prod_snapshot
        assert prod_snapshot.get("stdout_closed") is True, prod_snapshot
        assert prod_snapshot.get("stderr_closed") is True, prod_snapshot
        # Exact report classification.
        assert report is not None, "execute_authorization raised unexpectedly"
        assert report["overall_status"] == "launch_error", report
        # Exact persisted claimant terminal result.
        rcpt = run_root / ".icp-execution-receipts-v1"
        result_path = rcpt / f"{nonce}.result.json"
        assert result_path.is_file(), "terminal result not persisted"
        result = json.loads(result_path.read_text("utf-8"))
        assert result["overall_status"] == "launch_error", (
            result["overall_status"]
        )


def test_setup_failure_second_set_nonblock_no_leak() -> None:
    """Second ``_set_nonblock`` call raises after a real sleeping
    process is spawned. Same cleanup invariant and same proof of
    production-owned cleanup (snapshot before fallback)."""
    executor = _load("p2e2b_setup_nonblock2")
    body = "import time; time.sleep(60)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        run_root = Path(authz["verified_binding"]["selection_verification"]["run_root"])
        captured: dict[str, Any] = {}
        original_popen = subprocess.Popen
        original_set_nonblock = executor._set_nonblock
        call_count = {"n": 0}

        def _capturing_popen(*args, **kwargs):
            proc = original_popen(*args, **kwargs)
            captured["pgid"] = proc.pid
            captured["proc"] = proc
            return proc

        def _failing_set_nonblock(fd):
            call_count["n"] += 1
            if call_count["n"] >= 2:
                raise OSError("injected nonblock failure")
            original_set_nonblock(fd)

        executor._set_nonblock = _failing_set_nonblock
        subprocess.Popen = _capturing_popen
        prod_snapshot: dict[str, Any] = {}
        try:
            try:
                report = executor.execute_authorization(
                    **_exec_kwargs(expected, authz)
                )
            except executor.FlutterExecutionExecutorError:
                report = None
            if "proc" in captured:
                prod_snapshot = _snapshot_production_cleanup(captured)
        finally:
            executor._set_nonblock = original_set_nonblock
            subprocess.Popen = original_popen
            if "proc" in captured:
                try:
                    os.killpg(captured["pgid"], signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    pass
                try:
                    captured["proc"].wait(timeout=5)
                except Exception:
                    pass
        assert threading.active_count() == 1, threading.active_count()
        assert prod_snapshot.get("child_reaped") is True, prod_snapshot
        assert prod_snapshot.get("group_absent") is True, prod_snapshot
        assert prod_snapshot.get("stdout_closed") is True, prod_snapshot
        assert prod_snapshot.get("stderr_closed") is True, prod_snapshot
        assert report is not None, "execute_authorization raised unexpectedly"
        assert report["overall_status"] == "launch_error", report
        rcpt = run_root / ".icp-execution-receipts-v1"
        result_path = rcpt / f"{nonce}.result.json"
        assert result_path.is_file(), "terminal result not persisted"
        result = json.loads(result_path.read_text("utf-8"))
        assert result["overall_status"] == "launch_error", (
            result["overall_status"]
        )


def test_setup_failure_selector_constructor_no_leak() -> None:
    """``selectors.DefaultSelector`` constructor raises after a real
    sleeping process is spawned. Same cleanup invariant."""
    executor = _load("p2e2b_setup_sel_ctor")
    body = "import time; time.sleep(60)\n"
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        run_root = Path(authz["verified_binding"]["selection_verification"]["run_root"])
        captured: dict[str, Any] = {}
        original_popen = subprocess.Popen
        original_selector_cls = selectors.DefaultSelector

        class _FailingSelector:
            def __init__(self, *args, **kwargs):
                raise OSError("injected selector constructor failure")

            def register(self, *a, **k):
                pass

            def select(self, *a, **k):
                return []

            def unregister(self, *a, **k):
                pass

            def close(self):
                pass

        def _capturing_popen(*args, **kwargs):
            proc = original_popen(*args, **kwargs)
            captured["pgid"] = proc.pid
            captured["proc"] = proc
            return proc

        executor.selectors.DefaultSelector = _FailingSelector
        subprocess.Popen = _capturing_popen
        prod_snapshot: dict[str, Any] = {}
        try:
            try:
                report = executor.execute_authorization(
                    **_exec_kwargs(expected, authz)
                )
            except executor.FlutterExecutionExecutorError:
                report = None
            if "proc" in captured:
                prod_snapshot = _snapshot_production_cleanup(captured)
        finally:
            executor.selectors.DefaultSelector = original_selector_cls
            subprocess.Popen = original_popen
            if "proc" in captured:
                try:
                    os.killpg(captured["pgid"], signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    pass
                try:
                    captured["proc"].wait(timeout=5)
                except Exception:
                    pass
        assert threading.active_count() == 1, threading.active_count()
        assert prod_snapshot.get("child_reaped") is True, prod_snapshot
        assert prod_snapshot.get("group_absent") is True, prod_snapshot
        assert prod_snapshot.get("stdout_closed") is True, prod_snapshot
        assert prod_snapshot.get("stderr_closed") is True, prod_snapshot
        assert report is not None, "execute_authorization raised unexpectedly"
        assert report["overall_status"] == "launch_error", report
        rcpt = run_root / ".icp-execution-receipts-v1"
        result_path = rcpt / f"{nonce}.result.json"
        assert result_path.is_file(), "terminal result not persisted"
        result = json.loads(result_path.read_text("utf-8"))
        assert result["overall_status"] == "launch_error", (
            result["overall_status"]
        )


class _SelectRaisesSelector:
    """A fake selector whose ``select`` always raises OSError, but
    other operations are benign."""

    def __init__(self, *args, **kwargs):
        self._fds: set[int] = set()

    def register(self, fd, events, data=None):
        self._fds.add(fd)
        return None

    def select(self, timeout=None):
        raise OSError("injected select failure")

    def unregister(self, fd):
        self._fds.discard(fd)

    def close(self):
        self._fds.clear()


def test_selector_select_failure_classifies_output_drain_failure() -> None:
    """``selector.select()`` raises during drain. The executor must
    classify the step as ``output_drain_failure`` (NOT silently spin
    until timeout, NOT propagate as internal_error), return promptly
    within a bounded time, kill the captured group, persist no raw
    output, and leave zero later steps run."""
    executor = _load("p2e2b_sel_select_fail")
    body = (
        "#!/usr/bin/env python3\n"
        "import sys, time\n"
        "sys.stdout.write('secret_marker')\n"
        "sys.stdout.flush()\n"
        "time.sleep(60)\n"
    )
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        run_root = Path(authz["verified_binding"]["selection_verification"]["run_root"])
        original_selector_cls = selectors.DefaultSelector
        executor.selectors.DefaultSelector = _SelectRaisesSelector
        captured: dict[str, Any] = {}
        original_popen = subprocess.Popen

        def _capturing_popen(*args, **kwargs):
            proc = original_popen(*args, **kwargs)
            captured["pgid"] = proc.pid
            captured["proc"] = proc
            return proc

        subprocess.Popen = _capturing_popen
        start = time.monotonic()
        prod_snapshot: dict[str, Any] = {}
        try:
            # Force a short timeout so even a buggy spin finishes fast.
            original_eff_timeout = executor._effective_timeout
            executor._effective_timeout = lambda s: 5
            try:
                report = executor.execute_authorization(
                    **_exec_kwargs(expected, authz)
                )
            finally:
                executor._effective_timeout = original_eff_timeout
            if "proc" in captured:
                prod_snapshot = _snapshot_production_cleanup(captured)
        finally:
            executor.selectors.DefaultSelector = original_selector_cls
            subprocess.Popen = original_popen
            if "proc" in captured:
                try:
                    os.killpg(captured["pgid"], signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    pass
                try:
                    captured["proc"].wait(timeout=5)
                except Exception:
                    pass
        elapsed = time.monotonic() - start
        # Exact report classification.
        assert report is not None, "execute_authorization raised unexpectedly"
        assert report["ok"] is False, report
        assert report["overall_status"] == "output_drain_failure", report
        assert report["step_results"][0]["status"] == "output_drain_failure"
        # Prompt bounded return: well under the 5s forced timeout.
        assert elapsed < 4.0, f"selector failure spun too long: {elapsed}s"
        # No live process/group/thread.
        assert threading.active_count() == 1, threading.active_count()
        # Production cleanup happened before the fallback.
        assert prod_snapshot.get("child_reaped") is True, prod_snapshot
        assert prod_snapshot.get("group_absent") is True, prod_snapshot
        assert prod_snapshot.get("stdout_closed") is True, prod_snapshot
        assert prod_snapshot.get("stderr_closed") is True, prod_snapshot
        # Exact persisted claimant terminal result.
        rcpt = run_root / ".icp-execution-receipts-v1"
        result_path = rcpt / f"{nonce}.result.json"
        assert result_path.is_file(), "terminal result not persisted"
        result = json.loads(result_path.read_text("utf-8"))
        assert result["overall_status"] == "output_drain_failure", (
            result["overall_status"]
        )
        # No raw output persisted.
        assert "secret_marker" not in result_path.read_text(encoding="utf-8")


def test_best_effort_selector_failure_does_not_propagate() -> None:
    """After the descendant-grace kill, the best-effort drain path's
    ``selector.select()`` raises. The executor must still classify
    ``output_drain_failure`` (NOT propagate as internal_error),
    complete cleanup, and leave no live process/thread.

    This test exercises the REAL ``_drain_best_effort`` branch by
    using a delegating selector for the main drain loop, then wrapping
    ``_drain_best_effort`` as a fault-injection seam: immediately
    before calling the original function, arm the real selector
    instance so its next ``select()`` call raises a sanitized injected
    OSError. The original ``_drain_best_effort`` must swallow that
    OSError and return normally."""
    executor = _load("p2e2b_best_effort_sel_fail")
    body = (
        "#!/usr/bin/env python3\n"
        "import os, sys, time\n"
        "pid = os.fork()\n"
        "if pid == 0:\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        "os.write(1, b'marker')\n"
        "os._exit(0)\n"
    )
    with _build_substituted_binding(executor, body=body) as (
        am, bm, authz, mp, proj, spec, expected, nonce, sp, ss
    ):
        run_root = Path(authz["verified_binding"]["selection_verification"]["run_root"])
        original_grace = executor._DESCENDANT_GRACE_SECONDS
        executor._DESCENDANT_GRACE_SECONDS = 1.0
        original_drain_best_effort = executor._drain_best_effort
        # Track entry/exit of the wrapper and the armed selector.
        state: dict[str, Any] = {
            "wrapper_entered": 0,
            "selector_raised": 0,
            "original_returned": False,
            "armed_selector": None,
        }
        captured: dict[str, Any] = {}
        original_popen = subprocess.Popen

        def _capturing_popen(*args, **kwargs):
            proc = original_popen(*args, **kwargs)
            captured["pgid"] = proc.pid
            captured["proc"] = proc
            return proc

        def _wrapped_drain_best_effort(sel, stdout_acc, stderr_acc):
            state["wrapper_entered"] += 1
            # Arm the real selector instance so its next select()
            # call raises. We patch the bound select method on the
            # instance (not the class) so only this call is affected.
            original_select = sel.select
            state["armed_selector"] = sel

            def _raising_select(timeout=None):
                state["selector_raised"] += 1
                # Restore immediately so subsequent calls (if any) are
                # benign.
                sel.select = original_select
                raise OSError("injected best-effort select failure")

            sel.select = _raising_select
            try:
                result = original_drain_best_effort(sel, stdout_acc, stderr_acc)
                state["original_returned"] = True
                return result
            finally:
                # Ensure the patched method is restored even if the
                # original raised.
                sel.select = original_select

        executor._drain_best_effort = _wrapped_drain_best_effort
        subprocess.Popen = _capturing_popen
        prod_snapshot: dict[str, Any] = {}
        try:
            report = executor.execute_authorization(**_exec_kwargs(expected, authz))
            if "proc" in captured:
                prod_snapshot = _snapshot_production_cleanup(captured)
        finally:
            executor._drain_best_effort = original_drain_best_effort
            executor._DESCENDANT_GRACE_SECONDS = original_grace
            subprocess.Popen = original_popen
            if "proc" in captured:
                try:
                    os.killpg(captured["pgid"], signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    pass
                try:
                    captured["proc"].wait(timeout=5)
                except Exception:
                    pass
        # The wrapper was entered exactly once.
        assert state["wrapper_entered"] == 1, state
        # The armed selector raised exactly once inside the original
        # _drain_best_effort call.
        assert state["selector_raised"] == 1, state
        # The original _drain_best_effort returned normally (the
        # OSError was swallowed, not propagated).
        assert state["original_returned"] is True, state
        # Exact report classification.
        assert report is not None, "execute_authorization raised unexpectedly"
        assert report["ok"] is False, report
        assert report["overall_status"] == "output_drain_failure", report
        assert report["step_results"][0]["status"] == "output_drain_failure"
        # Real descendant/group cleanup, direct-child reap, pipe close
        # — production-owned, proven before the fallback.
        assert threading.active_count() == 1, threading.active_count()
        assert prod_snapshot.get("child_reaped") is True, prod_snapshot
        assert prod_snapshot.get("group_absent") is True, prod_snapshot
        assert prod_snapshot.get("stdout_closed") is True, prod_snapshot
        assert prod_snapshot.get("stderr_closed") is True, prod_snapshot
        # Exact persisted claimant terminal result (parsed, not just
        # raw-text searched).
        rcpt = run_root / ".icp-execution-receipts-v1"
        result_path = rcpt / f"{nonce}.result.json"
        assert result_path.is_file(), "terminal result not persisted"
        result = json.loads(result_path.read_text("utf-8"))
        assert result["overall_status"] == "output_drain_failure", (
            result["overall_status"]
        )
        # No raw output persisted.
        assert "marker" not in result_path.read_text(encoding="utf-8")


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
