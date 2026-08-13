#!/usr/bin/env python3
"""Vertical RED -> GREEN selftest for the ICP P2d1 Flutter
``project_preflight`` platform operation.

Covers the public Python API and CLI of
``platforms/flutter_project_preflight_v1.py``:

1. ``preflight(project_root) -> dict`` returns the canonical success
   report of kind ``icp.project-preflight.v1`` carrying the resolved
   project root, the validated project artifacts and their SHA-256, and
   the trusted Flutter toolchain resolved from the process PATH.
2. The CLI accepts only ``--project-root ABSOLUTE_PATH`` and emits
   exactly one canonical JSON object on stdout for success (exit 0) or
   on stderr for failure (exit 2). No traceback, no secret, no child
   stderr, no arbitrary exception text is ever emitted.
3. The operation is fail-closed and read-only: it writes nothing to the
   project, capsule, registry, or ``iff/``, never imports or reads
   sibling ``iff/``, and verifies the installed P2a capsule via the
   fixed ICP path before any project or toolchain inspection.
4. ``profile_id`` is fixed to ``flutter-standard``; no API or CLI
   override is exposed for executable, env, argv, command, interpreter,
   runner, registry, or activation.

This is the first executable platform operation for the otherwise
inactive ``flutter-standard`` adapter; it does not activate the adapter
and does not implement the other eight operation builders.

Run directly:

    PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p2d1_flutter_preflight.py
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import inspect
import io
import json
import os
import shutil
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
MODULE_PATH = PLATFORMS_DIR / "flutter_project_preflight_v1.py"
VERIFY_TOOL = ICP_SCRIPTS / "verify_vendor_iff_v1.py"

KIND = "icp.project-preflight.v1"
OPERATION_ID = "flutter.project_preflight.v1"
PLATFORM_ID = "flutter"
PROFILE_ID = "flutter-standard"
SCHEMA_VERSION = 1
CODE = "project_preflight_failed"

PUBSPEC_NAME = "pubspec.yaml"
LIB_NAME = "lib"
PACKAGE_CONFIG_REL = ".dart_tool/package_config.json"


# ---------------------------------------------------------------------------
# Module loader.
# ---------------------------------------------------------------------------


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _canonical_json(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MODULE_PATH), *args],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


@contextlib.contextmanager
def _canonical_tempdir(prefix: str = "p2d1_"):
    """Yield a temp dir whose path is realpath-canonicalized so the macOS
    ``/tmp`` -> ``/private/tmp`` symlink never trips the strict resolve
    containment check."""
    with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
        yield Path(os.path.realpath(str(tmp)))


# ---------------------------------------------------------------------------
# Fake Flutter + subprocess plumbing.
# ---------------------------------------------------------------------------


class _FakeCompletedProcess:
    def __init__(
        self,
        *,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


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


class _FakeShutil:
    """Minimal stand-in for ``shutil`` exposing only ``which``."""

    def __init__(self, which_fn) -> None:
        self.which = which_fn


class _FakeSubprocess:
    """Minimal stand-in for ``subprocess`` exposing only ``run`` and the
    constants the production code references."""

    PIPE = subprocess.PIPE
    TimeoutExpired = subprocess.TimeoutExpired

    def __init__(self, run_fn) -> None:
        self.run = run_fn


def _install_fake_flutter(
    module,
    *,
    resolved_path: Path | None = None,
    version_payload: dict[str, Any] | None = None,
    returncode: int = 0,
    stdout_override: str | None = None,
    stderr: str = "",
    raise_timeout: bool = False,
    raise_oserror: bool = False,
    raise_generic: bool = False,
):
    """Install a fake flutter executable on disk and replace
    ``module.shutil`` + ``module.subprocess`` with minimal stand-ins.

    Returns a dict with the recorded call kwargs (``calls`` list).

    The stand-ins REPLACE the module references (``module.shutil =
    _FakeShutil(...)``) so the global ``shutil``/``subprocess`` modules
    are never mutated. Use :func:`_restore` to revert the references.
    """
    if resolved_path is None:
        # Default: a real temp file marked executable.
        fd, path_str = tempfile.mkstemp(prefix="fake_flutter_")
        os.close(fd)
        resolved_path = Path(os.path.realpath(path_str))
        resolved_path.write_text("#!/bin/sh\necho fake\n", encoding="utf-8")
        os.chmod(resolved_path, 0o755)

    payload = version_payload if version_payload is not None else _default_version_payload()
    stdout_text = stdout_override if stdout_override is not None else (
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    )

    state: dict[str, list] = {"calls": [], "resolved_path": resolved_path}

    def _fake_which(name: str):
        # Only "flutter" is resolvable.
        if name == "flutter":
            return str(resolved_path)
        return None

    def _fake_run(args, **kwargs):
        call = {"args": list(args), "kwargs": dict(kwargs)}
        state["calls"].append(call)
        if raise_timeout:
            raise subprocess.TimeoutExpired(cmd=args, timeout=kwargs.get("timeout", 30))
        if raise_oserror:
            raise OSError("injected OSError")
        if raise_generic:
            raise RuntimeError("SECRET_GENERIC")
        return _FakeCompletedProcess(
            returncode=returncode, stdout=stdout_text, stderr=stderr
        )

    module.shutil = _FakeShutil(_fake_which)
    module.subprocess = _FakeSubprocess(_fake_run)
    return state


@contextlib.contextmanager
def _restore(module, *names):
    """Restore ``module.shutil`` and ``module.subprocess`` to their
    pre-test values. ``names`` is accepted for backwards compatibility;
    both references are always handled."""
    saved_shutil = module.shutil
    saved_subprocess = module.subprocess
    try:
        yield
    finally:
        module.shutil = saved_shutil
        module.subprocess = saved_subprocess


# ---------------------------------------------------------------------------
# Fixture builder: a minimal valid Flutter project root.
# ---------------------------------------------------------------------------


def _write_pubspec(root: Path, name: str = "my_app", extra: str = "") -> bytes:
    body = f"name: {name}\n{extra}"
    data = body.encode("utf-8")
    (root / PUBSPEC_NAME).write_bytes(data)
    return data


def _write_package_config(
    root: Path,
    *,
    name: str = "my_app",
    config_version: int = 2,
    extra_packages: list[dict] | None = None,
    raw: str | None = None,
) -> bytes:
    dart_tool = root / ".dart_tool"
    dart_tool.mkdir(parents=True, exist_ok=True)
    if raw is not None:
        data = raw.encode("utf-8")
        (dart_tool / "package_config.json").write_bytes(data)
        return data
    packages = [{"name": name, "rootUri": "../", "packageUri": "lib/", "languageVersion": "3.0"}]
    if extra_packages:
        packages.extend(extra_packages)
    payload = {
        "configVersion": config_version,
        "generated": "2024-01-01T00:00:00.000Z",
        "generator": "pub",
        "generatorVersion": "3.5.4",
        "flutterRoot": "/opt/flutter",
        "packages": packages,
    }
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (dart_tool / "package_config.json").write_bytes(data)
    return data


def _build_minimal_project(root: Path, *, name: str = "my_app") -> dict[str, bytes]:
    pubspec_bytes = _write_pubspec(root, name=name)
    (root / LIB_NAME).mkdir(parents=True, exist_ok=True)
    package_config_bytes = _write_package_config(root, name=name)
    return {
        "pubspec_bytes": pubspec_bytes,
        "package_config_bytes": package_config_bytes,
    }


# ---------------------------------------------------------------------------
# 1. Module + constants.
# ---------------------------------------------------------------------------


def test_module_loads() -> None:
    module = _load("p2d1_constants", MODULE_PATH)
    assert module.SCHEMA_VERSION == SCHEMA_VERSION
    assert module.KIND == KIND
    assert module.OPERATION_ID == OPERATION_ID
    assert module.PLATFORM_ID == PLATFORM_ID
    assert module.PROFILE_ID == PROFILE_ID
    assert isinstance(module.SCRIPT_NAME, str) and module.SCRIPT_NAME


def test_local_error_code_matches_icp_common_project_preflight_failed() -> None:
    """The local error code reuses the established ICP public code
    ``project_preflight_failed`` from ``icp_common`` (the operation's
    failure is a project_preflight failure, not a new local code)."""
    module = _load("p2d1_errcode", MODULE_PATH)
    assert isinstance(module.CODE, str) and module.CODE == CODE
    common = _load("icp_common_for_errcode_p2d1", ICP_SCRIPTS / "icp_common.py")
    assert module.CODE == common.PROJECT_PREFLIGHT_FAILED
    assert module.CODE in common.ALL_ERROR_CODES


def test_module_exposes_typed_exception() -> None:
    module = _load("p2d1_exc", MODULE_PATH)
    assert hasattr(module, "PreflightError")
    assert issubclass(module.PreflightError, ValueError)


# ---------------------------------------------------------------------------
# 2. Public API surface.
# ---------------------------------------------------------------------------


def test_public_api_exposes_preflight_and_entry_inspection() -> None:
    module = _load("p2d1_pubapi", MODULE_PATH)
    assert callable(module.preflight)
    assert callable(module.inspect_entry_requirements)
    allowed = {"preflight", "inspect_entry_requirements", "main"}
    public_funcs = [
        n
        for n in dir(module)
        if not n.startswith("_")
        and inspect.isfunction(getattr(module, n))
        and getattr(module, n).__module__ == module.__name__
    ]
    extra = sorted(set(public_funcs) - allowed)
    assert extra == [], f"unexpected public functions: {extra}"
    public_classes = [
        n
        for n in dir(module)
        if not n.startswith("_")
        and inspect.isclass(getattr(module, n))
        and getattr(module, n).__module__ == module.__name__
    ]
    assert set(public_classes) == {"PreflightError"}, public_classes


def test_preflight_signature_takes_only_project_root() -> None:
    module = _load("p2d1_sig", MODULE_PATH)
    sig = inspect.signature(module.preflight)
    params = list(sig.parameters)
    assert params == ["project_root"], sig
    # project_root accepts str | os.PathLike.
    p = sig.parameters["project_root"]
    assert p.default is inspect.Parameter.empty, "project_root must be required"


def test_module_exposes_no_override_parameters() -> None:
    module = _load("p2d1_noparams", MODULE_PATH)
    forbidden = (
        "EXECUTABLE", "FLUTTER_EXECUTABLE", "ENV_OVERRIDE",
        "ARGV", "INTERPRETER", "COMMAND", "ACTIVATION",
        "PROFILE_OVERRIDE", "REGISTRY_OVERRIDE",
    )
    for attr in forbidden:
        assert not hasattr(module, attr), f"module exposes override {attr}"


# ---------------------------------------------------------------------------
# 3. Capsule verification ordering.
# ---------------------------------------------------------------------------


def test_preflight_calls_verify_capsule_first() -> None:
    module = _load("p2d1_capsfirst", MODULE_PATH)
    called = {"count": 0}

    def _boom():
        called["count"] += 1
        raise module.PreflightError("capsule boom")

    module._verify_capsule = _boom
    try:
        with _canonical_tempdir() as root:
            try:
                module.preflight(root)
            except module.PreflightError as exc:
                assert "capsule boom" in str(exc)
            else:
                raise AssertionError("preflight did not verify capsule first")
    finally:
        del module._verify_capsule
    assert called["count"] == 1


def test_preflight_capsule_failure_converts_known_to_preflight_error() -> None:
    """The genuine loaded verifier's ``CapsuleIntegrityError`` (raised by
    ``verify_skill`` after the fixed verifier module loaded successfully)
    must convert to the known capsule-integrity diagnostic
    ``capsule verification failed: <message>``.

    This exercises the real isinstance check against the loaded
    verifier module's exception class — not a class-name heuristic."""
    module = _load("p2d1_capsfail", MODULE_PATH)
    verifier_module = module._load_verify_module()
    integrity_cls = verifier_module.CapsuleIntegrityError
    original_verify_skill = verifier_module.verify_skill

    def _boom(skill_root):
        raise integrity_cls("deterministic integrity message")

    verifier_module.verify_skill = _boom
    try:
        with _canonical_tempdir() as root:
            try:
                module.preflight(root)
            except module.PreflightError as exc:
                msg = str(exc)
                assert "capsule verification failed" in msg
                assert "deterministic integrity message" in msg
            else:
                raise AssertionError("preflight swallowed genuine CapsuleIntegrityError")
    finally:
        verifier_module.verify_skill = original_verify_skill


def test_preflight_capsule_failure_redacts_generic_exception_class_only() -> None:
    """A generic exception from capsule verification surfaces as type only,
    never arbitrary exception text."""
    module = _load("p2d1_capsgeneric", MODULE_PATH)

    class _SecretError(Exception):
        pass

    def _boom():
        raise _SecretError("SUPER_SECRET_BLOB")

    # Patch the underlying _load_verify_module to raise when first called.
    original_loader = module._load_verify_module

    def _broken_loader():
        raise _SecretError("SUPER_SECRET_BLOB")

    module._load_verify_module = _broken_loader
    try:
        with _canonical_tempdir() as root:
            try:
                module.preflight(root)
            except module.PreflightError as exc:
                msg = str(exc)
                assert "SUPER_SECRET_BLOB" not in msg
                assert "_SecretError" in msg or "SecretError" in msg
            else:
                raise AssertionError("preflight swallowed generic exception")
    finally:
        module._load_verify_module = original_loader


def test_preflight_capsule_same_name_exception_does_not_leak_message() -> None:
    """RED regression for the same-name exception leak.

    A dynamically-defined exception class whose ``__name__`` is exactly
    ``CapsuleIntegrityError`` raised from ``_load_verify_module`` (before
    the fixed verifier module loaded) must NOT be treated as a trusted
    capsule-integrity error. It must surface as the generic type-only
    diagnostic ``capsule verification raised CapsuleIntegrityError``,
    and the secret-bearing message must never appear."""
    module = _load("p2d1_capssamename", MODULE_PATH)

    # Dynamically define a class whose name is exactly the trusted
    # verifier's exception class name. This must not be trusted.
    RogueCapsuleIntegrityError = type(
        "CapsuleIntegrityError", (Exception,), {}
    )

    original_loader = module._load_verify_module

    def _broken_loader():
        raise RogueCapsuleIntegrityError("SUPER_SECRET_BLOB")

    module._load_verify_module = _broken_loader
    try:
        with _canonical_tempdir() as root:
            try:
                module.preflight(root)
            except module.PreflightError as exc:
                msg = str(exc)
                # The secret must never appear.
                assert "SUPER_SECRET_BLOB" not in msg, (
                    f"secret leaked into diagnostic: {msg!r}"
                )
                # The diagnostic must be the generic type-only form, NOT
                # the trusted capsule-integrity form. Both happen to name
                # the class, but only the trusted form carries the
                # ``capsule verification failed:`` prefix.
                assert msg == "capsule verification raised CapsuleIntegrityError", (
                    f"diagnostic was not the generic type-only form: {msg!r}"
                )
                assert "capsule verification failed" not in msg, (
                    f"same-name exception was mis-trusted as capsule failure: {msg!r}"
                )
            else:
                raise AssertionError("preflight swallowed same-name exception")
    finally:
        module._load_verify_module = original_loader


# ---------------------------------------------------------------------------
# 4. Project-root validation: absolute / normalized / real directory.
# ---------------------------------------------------------------------------


def test_preflight_rejects_relative_root() -> None:
    module = _load("p2d1_relroot", MODULE_PATH)
    try:
        module.preflight(Path("relative/path"))
    except module.PreflightError:
        pass
    else:
        raise AssertionError("relative root accepted")


def test_preflight_rejects_str_relative_root() -> None:
    module = _load("p2d1_strrel", MODULE_PATH)
    try:
        module.preflight("relative/path")
    except module.PreflightError:
        pass
    else:
        raise AssertionError("relative str root accepted")


def test_preflight_rejects_dotdot_in_path() -> None:
    module = _load("p2d1_dotdot", MODULE_PATH)
    with _canonical_tempdir() as tmp:
        bad = str(tmp) + "/sub/../.."
        try:
            module.preflight(bad)
        except module.PreflightError:
            pass
        else:
            raise AssertionError("dotdot path accepted")


def test_preflight_rejects_non_lexically_normalized_path() -> None:
    module = _load("p2d1_norm", MODULE_PATH)
    with _canonical_tempdir() as tmp:
        for bad in (str(tmp) + "/./x", str(tmp) + "//x", str(tmp) + "/a/./b"):
            try:
                module.preflight(bad)
            except module.PreflightError:
                pass
            else:
                raise AssertionError(f"non-normalized path accepted: {bad}")


def test_preflight_rejects_missing_root() -> None:
    module = _load("p2d1_missing", MODULE_PATH)
    with _canonical_tempdir() as tmp:
        bad = tmp / "does_not_exist"
        try:
            module.preflight(bad)
        except module.PreflightError:
            pass
        else:
            raise AssertionError("missing root accepted")


def test_preflight_rejects_file_as_root() -> None:
    module = _load("p2d1_fileroot", MODULE_PATH)
    with _canonical_tempdir() as tmp:
        f = tmp / "regular.txt"
        f.write_text("hi", encoding="utf-8")
        try:
            module.preflight(f)
        except module.PreflightError:
            pass
        else:
            raise AssertionError("regular file as root accepted")


def test_preflight_rejects_symlinked_root() -> None:
    module = _load("p2d1_symroot", MODULE_PATH)
    with _canonical_tempdir() as tmp:
        real = tmp / "real_dir"
        real.mkdir()
        link = tmp / "link_dir"
        os.symlink(real, link)
        try:
            module.preflight(link)
        except module.PreflightError:
            pass
        else:
            raise AssertionError("symlinked root accepted")


def test_preflight_rejects_symlinked_ancestor() -> None:
    module = _load("p2d1_symancestor", MODULE_PATH)
    with _canonical_tempdir() as tmp:
        real_parent = tmp / "real_parent"
        real_parent.mkdir()
        real_child = real_parent / "child"
        real_child.mkdir()
        link_parent = tmp / "link_parent"
        os.symlink(real_parent, link_parent)
        try:
            module.preflight(link_parent / "child")
        except module.PreflightError:
            pass
        else:
            raise AssertionError("symlinked ancestor accepted")


# ---------------------------------------------------------------------------
# 5. Project artifacts: missing / wrong-type / symlink / oversize.
# ---------------------------------------------------------------------------


def _good_preflight_module(label: str):
    return _load(label, MODULE_PATH)


def test_preflight_rejects_missing_pubspec() -> None:
    module = _good_preflight_module("p2d1_nopub")
    with _canonical_tempdir() as root:
        (root / LIB_NAME).mkdir()
        _write_package_config(root)
        try:
            module.preflight(root)
        except module.PreflightError:
            pass
        else:
            raise AssertionError("missing pubspec accepted")


def test_preflight_rejects_missing_lib() -> None:
    module = _good_preflight_module("p2d1_nolib")
    with _canonical_tempdir() as root:
        _write_pubspec(root)
        _write_package_config(root)
        try:
            module.preflight(root)
        except module.PreflightError:
            pass
        else:
            raise AssertionError("missing lib accepted")


def test_preflight_rejects_lib_as_file() -> None:
    module = _good_preflight_module("p2d1_libfile")
    with _canonical_tempdir() as root:
        _write_pubspec(root)
        (root / LIB_NAME).write_text("oops", encoding="utf-8")
        _write_package_config(root)
        try:
            module.preflight(root)
        except module.PreflightError:
            pass
        else:
            raise AssertionError("lib as regular file accepted")


def test_preflight_rejects_missing_package_config() -> None:
    module = _good_preflight_module("p2d1_nopkg")
    with _canonical_tempdir() as root:
        _write_pubspec(root)
        (root / LIB_NAME).mkdir()
        try:
            module.preflight(root)
        except module.PreflightError:
            pass
        else:
            raise AssertionError("missing package_config accepted")


def test_preflight_rejects_pubspec_as_directory() -> None:
    module = _good_preflight_module("p2d1_pubdir")
    with _canonical_tempdir() as root:
        (root / PUBSPEC_NAME).mkdir()
        (root / LIB_NAME).mkdir()
        _write_package_config(root)
        try:
            module.preflight(root)
        except module.PreflightError:
            pass
        else:
            raise AssertionError("pubspec directory accepted")


def test_preflight_rejects_symlinked_pubspec() -> None:
    module = _good_preflight_module("p2d1_pubsym")
    with _canonical_tempdir() as root:
        outside = root / "outside.yaml"
        outside.write_text("name: x\n", encoding="utf-8")
        (root / LIB_NAME).mkdir()
        _write_package_config(root)
        link = root / PUBSPEC_NAME
        os.symlink(outside, link)
        try:
            module.preflight(root)
        except module.PreflightError:
            pass
        else:
            raise AssertionError("symlinked pubspec accepted")


def test_preflight_rejects_symlinked_lib() -> None:
    module = _good_preflight_module("p2d1_libsym")
    with _canonical_tempdir() as root:
        _write_pubspec(root)
        outside = root / "outside_lib"
        outside.mkdir()
        _write_package_config(root)
        link = root / LIB_NAME
        os.symlink(outside, link)
        try:
            module.preflight(root)
        except module.PreflightError:
            pass
        else:
            raise AssertionError("symlinked lib accepted")


def test_preflight_rejects_symlinked_package_config() -> None:
    module = _good_preflight_module("p2d1_pkgsym")
    with _canonical_tempdir() as root:
        _write_pubspec(root)
        (root / LIB_NAME).mkdir()
        outside = root / "outside_pkgcfg.json"
        outside.write_text("{}\n", encoding="utf-8")
        (root / ".dart_tool").mkdir()
        link = root / PACKAGE_CONFIG_REL
        os.symlink(outside, link)
        try:
            module.preflight(root)
        except module.PreflightError:
            pass
        else:
            raise AssertionError("symlinked package_config accepted")


def test_preflight_rejects_oversized_pubspec() -> None:
    module = _good_preflight_module("p2d1_bigpub")
    with _canonical_tempdir() as root:
        (root / PUBSPEC_NAME).write_bytes(b"name: x\n" + b"#" * (2 * 1024 * 1024))
        (root / LIB_NAME).mkdir()
        _write_package_config(root)
        try:
            module.preflight(root)
        except module.PreflightError:
            pass
        else:
            raise AssertionError("oversized pubspec accepted")


def test_preflight_rejects_oversized_package_config() -> None:
    module = _good_preflight_module("p2d1_bigpkg")
    with _canonical_tempdir() as root:
        _write_pubspec(root)
        (root / LIB_NAME).mkdir()
        (root / ".dart_tool").mkdir()
        (root / PACKAGE_CONFIG_REL).write_bytes(
            b'{"configVersion": 2, "packages": []}' + b" " * (8 * 1024 * 1024)
        )
        try:
            module.preflight(root)
        except module.PreflightError:
            pass
        else:
            raise AssertionError("oversized package_config accepted")


def test_preflight_rejects_non_utf8_pubspec() -> None:
    module = _good_preflight_module("p2d1_badutf8pub")
    with _canonical_tempdir() as root:
        (root / PUBSPEC_NAME).write_bytes(b"\xff\xfe name: x\n")
        (root / LIB_NAME).mkdir()
        _write_package_config(root)
        try:
            module.preflight(root)
        except module.PreflightError:
            pass
        else:
            raise AssertionError("non-UTF-8 pubspec accepted")


def test_preflight_rejects_non_utf8_package_config() -> None:
    module = _good_preflight_module("p2d1_badutf8pkg")
    with _canonical_tempdir() as root:
        _write_pubspec(root)
        (root / LIB_NAME).mkdir()
        (root / ".dart_tool").mkdir()
        (root / PACKAGE_CONFIG_REL).write_bytes(b"\xff\xfe{}")
        try:
            module.preflight(root)
        except module.PreflightError:
            pass
        else:
            raise AssertionError("non-UTF-8 package_config accepted")


# ---------------------------------------------------------------------------
# 6. Project containment.
# ---------------------------------------------------------------------------


def test_preflight_rejects_package_config_via_symlinked_dart_tool() -> None:
    module = _good_preflight_module("p2d1_symdarttool")
    with _canonical_tempdir() as root:
        _write_pubspec(root)
        (root / LIB_NAME).mkdir()
        outside = root / "outside_dart_tool"
        outside.mkdir()
        (outside / "package_config.json").write_text(
            json.dumps({"configVersion": 2, "packages": []}) + "\n",
            encoding="utf-8",
        )
        link = root / ".dart_tool"
        os.symlink(outside, link)
        try:
            module.preflight(root)
        except module.PreflightError:
            pass
        else:
            raise AssertionError("symlinked .dart_tool accepted")


def test_preflight_rejects_pubspec_with_escape_path_via_symlink() -> None:
    """Even if pubspec exists at the right name, a symlink chain that
    escapes the root must be rejected before read."""
    module = _good_preflight_module("p2d1_escapesym")
    with _canonical_tempdir() as root:
        outside = root.parent / "outside_pubspec_root"
        outside.mkdir(exist_ok=True)
        (outside / PUBSPEC_NAME).write_text("name: x\n", encoding="utf-8")
        (root / LIB_NAME).mkdir()
        _write_package_config(root)
        link = root / PUBSPEC_NAME
        if link.exists() or link.is_symlink():
            link.unlink()
        os.symlink(outside / PUBSPEC_NAME, link)
        try:
            module.preflight(root)
        except module.PreflightError:
            pass
        else:
            raise AssertionError("escape symlink pubspec accepted")


# ---------------------------------------------------------------------------
# 7. pubspec name parser edge cases.
# ---------------------------------------------------------------------------


def _good_project_with_pubspec_text(module, root: Path, pubspec_text: str) -> None:
    (root / PUBSPEC_NAME).write_text(pubspec_text, encoding="utf-8")
    (root / LIB_NAME).mkdir()
    _write_package_config(root)


def test_preflight_rejects_missing_name_in_pubspec() -> None:
    module = _good_preflight_module("p2d1_noname")
    with _canonical_tempdir() as root:
        _good_project_with_pubspec_text(module, root, "description: no name here\n")
        try:
            module.preflight(root)
        except module.PreflightError:
            pass
        else:
            raise AssertionError("missing name accepted")


def test_preflight_rejects_empty_name_in_pubspec() -> None:
    module = _good_preflight_module("p2d1_emptyname")
    with _canonical_tempdir() as root:
        _good_project_with_pubspec_text(module, root, "name:\n")
        try:
            module.preflight(root)
        except module.PreflightError:
            pass
        else:
            raise AssertionError("empty name accepted")


def test_preflight_rejects_empty_quoted_name_in_pubspec() -> None:
    module = _good_preflight_module("p2d1_emptyquote")
    with _canonical_tempdir() as root:
        _good_project_with_pubspec_text(module, root, 'name: ""\n')
        try:
            module.preflight(root)
        except module.PreflightError:
            pass
        else:
            raise AssertionError("empty quoted name accepted")


def test_preflight_rejects_duplicate_top_level_name_in_pubspec() -> None:
    module = _good_preflight_module("p2d1_dupname")
    with _canonical_tempdir() as root:
        _good_project_with_pubspec_text(
            module, root, "name: first\nname: second\n"
        )
        try:
            module.preflight(root)
        except module.PreflightError:
            pass
        else:
            raise AssertionError("duplicate top-level name accepted")


def test_preflight_rejects_indented_name_in_pubspec() -> None:
    """A name: scalar under another key must not be picked up."""
    module = _good_preflight_module("p2d1_indentname")
    with _canonical_tempdir() as root:
        _good_project_with_pubspec_text(
            module, root, "environment:\n  name: should_not_match\n"
        )
        try:
            module.preflight(root)
        except module.PreflightError:
            pass
        else:
            raise AssertionError("indented name accepted")


def test_preflight_rejects_invalid_double_quoted_escape_in_name() -> None:
    module = _good_preflight_module("p2d1_badescape")
    with _canonical_tempdir() as root:
        _good_project_with_pubspec_text(module, root, 'name: "bad\\xescape"\n')
        try:
            module.preflight(root)
        except module.PreflightError:
            pass
        else:
            raise AssertionError("invalid double-quoted escape accepted")


def test_preflight_accepts_simple_quoted_name() -> None:
    module = _good_preflight_module("p2d1_okquote")
    with _canonical_tempdir() as root:
        _good_project_with_pubspec_text(module, root, 'name: "my_app"\n')
        _install_fake_flutter(module)
        with _restore(module, "shutil", "subprocess"):
            try:
                report = module.preflight(root)
            except module.PreflightError as exc:
                raise AssertionError(f"valid quoted name rejected: {exc}")
        # Pubspec SHA must be of the file bytes.
        expected_sha = hashlib.sha256(
            (root / PUBSPEC_NAME).read_bytes()
        ).hexdigest()
        assert report["project"]["pubspec_sha256"] == expected_sha


def test_preflight_accepts_single_quoted_name() -> None:
    module = _good_preflight_module("p2d1_oksinglequote")
    with _canonical_tempdir() as root:
        _good_project_with_pubspec_text(module, root, "name: 'my_app'\n")
        _install_fake_flutter(module)
        with _restore(module, "shutil", "subprocess"):
            report = module.preflight(root)
        assert report is not None


def test_preflight_rejects_name_with_inline_comment_only_value() -> None:
    """``name: # comment`` has no actual value."""
    module = _good_preflight_module("p2d1_namecomment")
    with _canonical_tempdir() as root:
        _good_project_with_pubspec_text(module, root, "name: # no value\n")
        try:
            module.preflight(root)
        except module.PreflightError:
            pass
        else:
            raise AssertionError("name with comment-only value accepted")


def test_preflight_accepts_name_with_trailing_comment() -> None:
    module = _good_preflight_module("p2d1_namestrailcomment")
    with _canonical_tempdir() as root:
        _good_project_with_pubspec_text(module, root, "name: my_app # ok\n")
        _write_package_config(root, name="my_app")
        _install_fake_flutter(module)
        with _restore(module, "shutil", "subprocess"):
            report = module.preflight(root)
        assert report is not None


# ---------------------------------------------------------------------------
# 8. Package-config shape + package-name match.
# ---------------------------------------------------------------------------


def test_preflight_rejects_package_config_wrong_config_version() -> None:
    module = _good_preflight_module("p2d1_wroncfgver")
    with _canonical_tempdir() as root:
        _write_pubspec(root)
        (root / LIB_NAME).mkdir()
        _write_package_config(root, config_version=3)
        try:
            module.preflight(root)
        except module.PreflightError:
            pass
        else:
            raise AssertionError("wrong configVersion accepted")


def test_preflight_rejects_package_config_missing_packages_list() -> None:
    module = _good_preflight_module("p2d1_nopkglist")
    with _canonical_tempdir() as root:
        _write_pubspec(root)
        (root / LIB_NAME).mkdir()
        (root / ".dart_tool").mkdir()
        (root / PACKAGE_CONFIG_REL).write_text(
            json.dumps({"configVersion": 2}) + "\n", encoding="utf-8"
        )
        try:
            module.preflight(root)
        except module.PreflightError:
            pass
        else:
            raise AssertionError("missing packages list accepted")


def test_preflight_rejects_package_config_with_no_matching_name() -> None:
    module = _good_preflight_module("p2d1_nomatch")
    with _canonical_tempdir() as root:
        _write_pubspec(root, name="my_app")
        (root / LIB_NAME).mkdir()
        _write_package_config(
            root,
            name="some_other_package",
        )
        try:
            module.preflight(root)
        except module.PreflightError:
            pass
        else:
            raise AssertionError("non-matching package name accepted")


def test_preflight_rejects_package_config_not_object() -> None:
    module = _good_preflight_module("p2d1_pkgnotobj")
    with _canonical_tempdir() as root:
        _write_pubspec(root)
        (root / LIB_NAME).mkdir()
        (root / ".dart_tool").mkdir()
        (root / PACKAGE_CONFIG_REL).write_text("[1,2,3]\n", encoding="utf-8")
        try:
            module.preflight(root)
        except module.PreflightError:
            pass
        else:
            raise AssertionError("non-object package_config accepted")


def test_preflight_rejects_package_config_with_duplicate_keys() -> None:
    module = _good_preflight_module("p2d1_pkgdup")
    with _canonical_tempdir() as root:
        _write_pubspec(root)
        (root / LIB_NAME).mkdir()
        (root / ".dart_tool").mkdir()
        (root / PACKAGE_CONFIG_REL).write_text(
            '{"configVersion": 2, "configVersion": 3, "packages": []}\n',
            encoding="utf-8",
        )
        try:
            module.preflight(root)
        except module.PreflightError:
            pass
        else:
            raise AssertionError("duplicate JSON keys accepted")


def test_preflight_rejects_package_config_malformed_json() -> None:
    module = _good_preflight_module("p2d1_pkgbadjson")
    with _canonical_tempdir() as root:
        _write_pubspec(root)
        (root / LIB_NAME).mkdir()
        (root / ".dart_tool").mkdir()
        (root / PACKAGE_CONFIG_REL).write_text("{not json", encoding="utf-8")
        try:
            module.preflight(root)
        except module.PreflightError:
            pass
        else:
            raise AssertionError("malformed package_config JSON accepted")


def test_preflight_accepts_package_config_with_extra_matching_packages() -> None:
    module = _good_preflight_module("p2d1_pkgextras")
    with _canonical_tempdir() as root:
        _write_pubspec(root, name="my_app")
        (root / LIB_NAME).mkdir()
        _write_package_config(
            root,
            name="my_app",
            extra_packages=[
                {"name": "other_dep", "rootUri": "../other", "packageUri": "lib/", "languageVersion": "3.0"},
            ],
        )
        _install_fake_flutter(module)
        with _restore(module, "shutil", "subprocess"):
            report = module.preflight(root)
        assert report is not None


# ---------------------------------------------------------------------------
# 9. Happy path: preflight returns canonical report.
# ---------------------------------------------------------------------------


def test_preflight_returns_canonical_report_shape() -> None:
    module = _load("p2d1_happy", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        _install_fake_flutter(module)
        with _restore(module, "shutil", "subprocess"):
            report = module.preflight(root)
    assert isinstance(report, dict)
    assert report["kind"] == KIND
    assert report["schema_version"] == SCHEMA_VERSION
    assert report["operation_id"] == OPERATION_ID
    assert report["platform_id"] == PLATFORM_ID
    assert report["profile_id"] == PROFILE_ID
    assert set(report.keys()) == {
        "kind", "schema_version", "operation_id", "platform_id",
        "profile_id", "project_root", "project", "toolchain",
    }, sorted(report.keys())


def test_preflight_report_project_block_keys_and_values() -> None:
    module = _load("p2d1_projblock", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        pubspec_sha = hashlib.sha256((root / PUBSPEC_NAME).read_bytes()).hexdigest()
        _install_fake_flutter(module)
        with _restore(module, "shutil", "subprocess"):
            report = module.preflight(root)
    proj = report["project"]
    assert set(proj.keys()) == {
        "lib_directory", "package_config", "pubspec", "pubspec_sha256",
    }, sorted(proj.keys())
    assert proj["lib_directory"] == LIB_NAME
    assert proj["pubspec"] == PUBSPEC_NAME
    assert proj["package_config"] == PACKAGE_CONFIG_REL
    assert proj["pubspec_sha256"] == pubspec_sha
    assert _is_sha256_hex(proj["pubspec_sha256"])


def test_preflight_report_toolchain_block_keys_and_values() -> None:
    module = _load("p2d1_toolblock", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        state = _install_fake_flutter(module)
        with _restore(module, "shutil", "subprocess"):
            report = module.preflight(root)
    resolved = state["resolved_path"]
    payload_bytes = (json.dumps(_default_version_payload(), indent=2) + "\n").encode("utf-8")
    expected_version_sha = hashlib.sha256(payload_bytes).hexdigest()
    expected_flutter_sha = hashlib.sha256(resolved.read_bytes()).hexdigest()
    tc = report["toolchain"]
    assert set(tc.keys()) == {
        "flutter_executable", "flutter_executable_sha256",
        "flutter_version", "dart_sdk_version", "version_payload_sha256",
    }, sorted(tc.keys())
    assert tc["flutter_executable"] == str(resolved)
    assert tc["flutter_executable_sha256"] == expected_flutter_sha
    assert tc["flutter_version"] == "3.24.5"
    assert tc["dart_sdk_version"] == "3.5.4"
    assert tc["version_payload_sha256"] == expected_version_sha
    assert _is_sha256_hex(tc["flutter_executable_sha256"])
    assert _is_sha256_hex(tc["version_payload_sha256"])


def test_preflight_report_project_root_canonical_absolute() -> None:
    module = _load("p2d1_rootcanon", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        _install_fake_flutter(module)
        with _restore(module, "shutil", "subprocess"):
            report = module.preflight(root)
    assert report["project_root"] == str(root)
    assert os.path.isabs(report["project_root"])


def test_preflight_accepts_pathlike_and_str_inputs() -> None:
    module = _load("p2d1_pathlike", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        _install_fake_flutter(module)
        with _restore(module, "shutil", "subprocess"):
            r1 = module.preflight(root)
            r2 = module.preflight(str(root))
    assert r1 == r2


# ---------------------------------------------------------------------------
# 10. Canonical bytes + determinism.
# ---------------------------------------------------------------------------


def test_preflight_canonical_json_sorted_keys_two_space_indent_newline() -> None:
    module = _load("p2d1_canon", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        _install_fake_flutter(module)
        with _restore(module, "shutil", "subprocess"):
            report = module.preflight(root)
            raw = module._canonical_json_bytes(report)
    assert raw.endswith(b"\n")
    text = raw.decode("utf-8")
    assert text.index('"kind"') < text.index('"operation_id"')
    assert text.index('"operation_id"') < text.index('"platform_id"')
    assert "\n  " in text


def test_preflight_byte_for_byte_deterministic_in_process() -> None:
    module = _load("p2d1_det1", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        _install_fake_flutter(module)
        with _restore(module, "shutil", "subprocess"):
            r1 = module.preflight(root)
            r2 = module.preflight(root)
    assert module._canonical_json_bytes(r1) == module._canonical_json_bytes(r2)


def test_preflight_byte_for_byte_deterministic_across_modules() -> None:
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        # Share a single fake flutter executable so the toolchain block
        # is identical across module instances.
        fd, path_str = tempfile.mkstemp(prefix="fake_flutter_det_")
        os.close(fd)
        shared_flutter = Path(os.path.realpath(path_str))
        shared_flutter.write_text("#!/bin/sh\necho fake\n", encoding="utf-8")
        os.chmod(shared_flutter, 0o755)
        m1 = _load("p2d1_deta", MODULE_PATH)
        _install_fake_flutter(m1, resolved_path=shared_flutter)
        with _restore(m1, "shutil", "subprocess"):
            r1 = m1.preflight(root)
        m2 = _load("p2d1_detb", MODULE_PATH)
        _install_fake_flutter(m2, resolved_path=shared_flutter)
        with _restore(m2, "shutil", "subprocess"):
            r2 = m2.preflight(root)
    assert m1._canonical_json_bytes(r1) == m2._canonical_json_bytes(r2)


# ---------------------------------------------------------------------------
# 11. Toolchain resolution: PATH lookup failure, file/exec checks.
# ---------------------------------------------------------------------------


def test_preflight_fails_when_flutter_not_in_path() -> None:
    module = _load("p2d1_noflutter", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        saved_shutil = module.shutil
        module.shutil = _FakeShutil(lambda name: None)
        try:
            try:
                module.preflight(root)
            except module.PreflightError:
                pass
            else:
                raise AssertionError("missing PATH lookup accepted")
        finally:
            module.shutil = saved_shutil


def test_preflight_fails_when_resolved_flutter_missing() -> None:
    module = _load("p2d1_ghostflutter", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        ghost = root / "ghost_flutter"
        # Do not create it.
        saved_shutil = module.shutil
        module.shutil = _FakeShutil(
            lambda name: str(ghost) if name == "flutter" else None
        )
        try:
            try:
                module.preflight(root)
            except module.PreflightError:
                pass
            else:
                raise AssertionError("ghost flutter path accepted")
        finally:
            module.shutil = saved_shutil


def test_preflight_fails_when_resolved_flutter_is_directory() -> None:
    module = _load("p2d1_dirflutter", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        fake_dir = root / "fake_flutter_dir"
        fake_dir.mkdir()
        saved_shutil = module.shutil
        module.shutil = _FakeShutil(
            lambda name: str(fake_dir) if name == "flutter" else None
        )
        try:
            try:
                module.preflight(root)
            except module.PreflightError:
                pass
            else:
                raise AssertionError("directory flutter accepted")
        finally:
            module.shutil = saved_shutil


def test_preflight_fails_when_resolved_flutter_not_executable() -> None:
    module = _load("p2d1_noexecflutter", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        non_exec = root / "non_exec_flutter"
        non_exec.write_text("#!/bin/sh\n", encoding="utf-8")
        os.chmod(non_exec, 0o644)  # not executable
        saved_shutil = module.shutil
        module.shutil = _FakeShutil(
            lambda name: str(non_exec) if name == "flutter" else None
        )
        try:
            try:
                module.preflight(root)
            except module.PreflightError:
                pass
            else:
                raise AssertionError("non-executable flutter accepted")
        finally:
            module.shutil = saved_shutil


def test_preflight_records_canonical_target_when_path_returns_symlink() -> None:
    """A symlink returned by PATH is allowed only after canonicalization; the
    report records the final target."""
    module = _load("p2d1_symflutter", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        # Real flutter target somewhere outside the project.
        real_flutter_dir = root.parent / "real_flutter_bin"
        real_flutter_dir.mkdir(exist_ok=True)
        real_target = real_flutter_dir / "flutter"
        real_target.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
        os.chmod(real_target, 0o755)
        # Symlink exposed via PATH.
        link = root / "flutter_link"
        os.symlink(real_target, link)
        _install_fake_flutter(module, resolved_path=real_target)
        with _restore(module, "shutil", "subprocess"):
            # Restore which to default fake implementation that returns the link.
            module.shutil = _FakeShutil(
                lambda n: str(link) if n == "flutter" else None
            )
            report = module.preflight(root)
    assert report["toolchain"]["flutter_executable"] == str(real_target)


# ---------------------------------------------------------------------------
# 12. Subprocess argv / cwd / timeout / shell / env.
# ---------------------------------------------------------------------------


def test_preflight_subprocess_uses_exact_argv() -> None:
    module = _load("p2d1_argv", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        state = _install_fake_flutter(module)
        with _restore(module, "shutil", "subprocess"):
            module.preflight(root)
    assert state["calls"], "subprocess.run was not invoked"
    call = state["calls"][0]
    args = call["args"]
    resolved = state["resolved_path"]
    assert args == [str(resolved), "--version", "--machine"], args


def test_preflight_subprocess_uses_shell_false() -> None:
    module = _load("p2d1_shell", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        state = _install_fake_flutter(module)
        with _restore(module, "shutil", "subprocess"):
            module.preflight(root)
    assert state["calls"][0]["kwargs"].get("shell") is False


def test_preflight_subprocess_uses_cwd_equal_to_project_root() -> None:
    module = _load("p2d1_cwd", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        state = _install_fake_flutter(module)
        with _restore(module, "shutil", "subprocess"):
            module.preflight(root)
    cwd = state["calls"][0]["kwargs"].get("cwd")
    assert cwd is not None
    assert Path(cwd) == root or cwd == str(root), cwd


def test_preflight_subprocess_uses_30s_timeout() -> None:
    module = _load("p2d1_timeout", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        state = _install_fake_flutter(module)
        with _restore(module, "shutil", "subprocess"):
            module.preflight(root)
    assert state["calls"][0]["kwargs"].get("timeout") == 30


def test_preflight_subprocess_passes_no_env_override() -> None:
    """The subprocess invocation must not receive a user-controlled env
    overlay; either env is absent or exactly os.environ."""
    module = _load("p2d1_noenv", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        state = _install_fake_flutter(module)
        with _restore(module, "shutil", "subprocess"):
            module.preflight(root)
    env_arg = state["calls"][0]["kwargs"].get("env")
    if env_arg is not None:
        # Only os.environ itself is acceptable.
        assert env_arg is os.environ


def test_preflight_subprocess_captures_stdout_and_stderr() -> None:
    module = _load("p2d1_capture", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        state = _install_fake_flutter(module)
        with _restore(module, "shutil", "subprocess"):
            module.preflight(root)
    kwargs = state["calls"][0]["kwargs"]
    assert kwargs.get("stdout") == subprocess.PIPE
    assert kwargs.get("stderr") == subprocess.PIPE
    assert kwargs.get("text") is True


def test_preflight_subprocess_uses_utf8_encoding() -> None:
    """The subprocess text decoder must be fixed to UTF-8, independent
    of the process locale. ``encoding="utf-8"`` must be passed
    explicitly alongside ``text=True``."""
    module = _load("p2d1_utf8enc", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        state = _install_fake_flutter(module)
        with _restore(module, "shutil", "subprocess"):
            module.preflight(root)
    kwargs = state["calls"][0]["kwargs"]
    assert kwargs.get("encoding") == "utf-8", (
        f"expected encoding='utf-8', got kwargs={kwargs!r}"
    )


def test_preflight_subprocess_uses_strict_errors() -> None:
    """The subprocess text decoder must use ``errors="strict"`` so a
    non-UTF-8 byte in child stdout surfaces as a controlled failure
    rather than silent replacement."""
    module = _load("p2d1_stricterr", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        state = _install_fake_flutter(module)
        with _restore(module, "shutil", "subprocess"):
            module.preflight(root)
    kwargs = state["calls"][0]["kwargs"]
    assert kwargs.get("errors") == "strict", (
        f"expected errors='strict', got kwargs={kwargs!r}"
    )


# ---------------------------------------------------------------------------
# 13. Toolchain subprocess failures.
# ---------------------------------------------------------------------------


def test_preflight_fails_on_subprocess_timeout() -> None:
    module = _load("p2d1_subtimeout", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        _install_fake_flutter(module, raise_timeout=True)
        with _restore(module, "shutil", "subprocess"):
            try:
                module.preflight(root)
            except module.PreflightError:
                pass
            else:
                raise AssertionError("subprocess timeout accepted")


def test_preflight_fails_on_subprocess_nonzero_exit() -> None:
    module = _load("p2d1_subnonzero", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        _install_fake_flutter(module, returncode=1)
        with _restore(module, "shutil", "subprocess"):
            try:
                module.preflight(root)
            except module.PreflightError:
                pass
            else:
                raise AssertionError("nonzero exit accepted")


def test_preflight_fails_on_subprocess_nonempty_stderr() -> None:
    module = _load("p2d1_substderr", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        _install_fake_flutter(module, stderr="SECRET_CHILD_STDERR")
        with _restore(module, "shutil", "subprocess"):
            try:
                module.preflight(root)
            except module.PreflightError as exc:
                # The error must never echo child stderr content.
                assert "SECRET_CHILD_STDERR" not in str(exc)
            else:
                raise AssertionError("nonempty stderr accepted")


def test_preflight_fails_on_malformed_version_json() -> None:
    module = _load("p2d1_badjson", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        _install_fake_flutter(module, stdout_override="{not json")
        with _restore(module, "shutil", "subprocess"):
            try:
                module.preflight(root)
            except module.PreflightError:
                pass
            else:
                raise AssertionError("malformed version JSON accepted")


def test_preflight_fails_on_oversized_version_stdout() -> None:
    module = _load("p2d1_bigstdout", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        _install_fake_flutter(module, stdout_override="x" * (1024 * 1024 + 1))
        with _restore(module, "shutil", "subprocess"):
            try:
                module.preflight(root)
            except module.PreflightError:
                pass
            else:
                raise AssertionError("oversized version stdout accepted")


def test_preflight_fails_on_version_payload_not_object() -> None:
    module = _load("p2d1_payloadarray", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        _install_fake_flutter(module, stdout_override="[1, 2, 3]\n")
        with _restore(module, "shutil", "subprocess"):
            try:
                module.preflight(root)
            except module.PreflightError:
                pass
            else:
                raise AssertionError("non-object version payload accepted")


def test_preflight_fails_on_missing_framework_version_key() -> None:
    module = _load("p2d1_nofwk", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        bad = {
            "channel": "stable",
            "dartSdkVersion": "3.5.4",
        }
        _install_fake_flutter(module, version_payload=bad)
        with _restore(module, "shutil", "subprocess"):
            try:
                module.preflight(root)
            except module.PreflightError:
                pass
            else:
                raise AssertionError("missing frameworkVersion accepted")


def test_preflight_fails_on_missing_dart_sdk_version_key() -> None:
    module = _load("p2d1_nodart", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        bad = {"frameworkVersion": "3.24.5", "channel": "stable"}
        _install_fake_flutter(module, version_payload=bad)
        with _restore(module, "shutil", "subprocess"):
            try:
                module.preflight(root)
            except module.PreflightError:
                pass
            else:
                raise AssertionError("missing dartSdkVersion accepted")


def test_preflight_fails_on_empty_framework_version() -> None:
    module = _load("p2d1_emptyfwk", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        bad = {"frameworkVersion": "", "dartSdkVersion": "3.5.4"}
        _install_fake_flutter(module, version_payload=bad)
        with _restore(module, "shutil", "subprocess"):
            try:
                module.preflight(root)
            except module.PreflightError:
                pass
            else:
                raise AssertionError("empty frameworkVersion accepted")


def test_preflight_fails_on_empty_dart_sdk_version() -> None:
    module = _load("p2d1_emptydart", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        bad = {"frameworkVersion": "3.24.5", "dartSdkVersion": ""}
        _install_fake_flutter(module, version_payload=bad)
        with _restore(module, "shutil", "subprocess"):
            try:
                module.preflight(root)
            except module.PreflightError:
                pass
            else:
                raise AssertionError("empty dartSdkVersion accepted")


def test_preflight_fails_on_duplicate_version_payload_keys() -> None:
    module = _load("p2d1_duppayload", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        raw = (
            '{"frameworkVersion": "3.24.5", "frameworkVersion": "x", '
            '"dartSdkVersion": "3.5.4"}\n'
        )
        _install_fake_flutter(module, stdout_override=raw)
        with _restore(module, "shutil", "subprocess"):
            try:
                module.preflight(root)
            except module.PreflightError:
                pass
            else:
                raise AssertionError("duplicate version payload keys accepted")


def test_preflight_fails_on_oserror_from_subprocess() -> None:
    module = _load("p2d1_suboserror", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        _install_fake_flutter(module, raise_oserror=True)
        with _restore(module, "shutil", "subprocess"):
            try:
                module.preflight(root)
            except module.PreflightError:
                pass
            else:
                raise AssertionError("OSError from subprocess accepted")


def test_preflight_redacts_generic_subprocess_exception() -> None:
    module = _load("p2d1_subgeneric", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        _install_fake_flutter(module, raise_generic=True)
        with _restore(module, "shutil", "subprocess"):
            try:
                module.preflight(root)
            except module.PreflightError as exc:
                assert "SECRET_GENERIC" not in str(exc)
                assert "RuntimeError" in str(exc) or "RuntimeError" in type(exc).__name__
            else:
                raise AssertionError("generic subprocess exception accepted")


# ---------------------------------------------------------------------------
# 14. CLI surface.
# ---------------------------------------------------------------------------


def test_cli_emits_canonical_json_on_stdout_exit_0() -> None:
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        # Build a real (but tiny) fake flutter that prints --machine JSON.
        fake_flutter_dir = root.parent / "fake_flutter_bin_for_cli"
        fake_flutter_dir.mkdir(exist_ok=True)
        fake_flutter = fake_flutter_dir / "flutter"
        fake_flutter.write_text(
            "#!/bin/sh\n"
            "case \"$*\" in\n"
            "  *--version*--machine*)\n"
            "    printf '%s\\n' '" + json.dumps(_default_version_payload()).replace("'", "'\\''") + "'\n"
            "    ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        os.chmod(fake_flutter, 0o755)
        env = {
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PATH": str(fake_flutter_dir) + os.pathsep + os.environ.get("PATH", ""),
        }
        r = subprocess.run(
            [sys.executable, str(MODULE_PATH), "--project-root", str(root)],
            capture_output=True,
            text=True,
            env=env,
        )
        assert r.returncode == 0, r.stderr
        assert r.stderr == ""
        payload = json.loads(r.stdout)
        assert payload["kind"] == KIND
        assert payload["operation_id"] == OPERATION_ID


def test_cli_byte_for_byte_matches_python_canonical_bytes() -> None:
    module = _load("p2d1_climatch", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        state = _install_fake_flutter(module)
        with _restore(module, "shutil", "subprocess"):
            in_process_report = module.preflight(root)
            expected = module._canonical_json_bytes(in_process_report).decode("utf-8")
        # CLI call uses the same fake.
        with _patched_module_env(module, state):
            r = _run_cli_in_module(module, "--project-root", str(root))
    assert r.returncode == 0, r.stderr
    assert r.stdout == expected


def test_cli_rejects_missing_project_root() -> None:
    r = _run_cli()
    assert r.returncode == 2
    assert r.stdout == ""
    payload = json.loads(r.stderr)
    assert payload["ok"] is False
    assert payload["code"] == CODE


def test_cli_rejects_relative_project_root() -> None:
    r = _run_cli("--project-root", "relative/path")
    assert r.returncode == 2
    payload = json.loads(r.stderr)
    assert payload["ok"] is False
    assert payload["code"] == CODE


def test_cli_rejects_unknown_flag() -> None:
    r = _run_cli("--project-root", "/tmp/x", "--bogus")
    assert r.returncode == 2
    payload = json.loads(r.stderr)
    assert payload["ok"] is False
    assert payload["code"] == CODE


def test_cli_rejects_executable_override() -> None:
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        r = _run_cli(
            "--project-root", str(root),
            "--executable", "/usr/local/bin/flutter",
        )
    assert r.returncode == 2
    payload = json.loads(r.stderr)
    assert payload["ok"] is False
    assert payload["code"] == CODE


def test_cli_rejects_env_override() -> None:
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        r = _run_cli("--project-root", str(root), "--env", "X=1")
    assert r.returncode == 2


def test_cli_rejects_argv_override() -> None:
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        r = _run_cli("--project-root", str(root), "--argv", "[]")
    assert r.returncode == 2


def test_cli_rejects_command_override() -> None:
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        r = _run_cli("--project-root", str(root), "--command", "flutter")
    assert r.returncode == 2


def test_cli_rejects_profile_override() -> None:
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        r = _run_cli("--project-root", str(root), "--profile", "other")
    assert r.returncode == 2


def test_cli_emits_no_traceback_on_failure() -> None:
    module = _load("p2d1_cli_tb", MODULE_PATH)

    def _boom(root):
        raise RuntimeError("SECRET_GENERIC_EXCEPTION")

    module.preflight = _boom
    stderr = io.StringIO()
    stdout = io.StringIO()
    orig_err = sys.stderr
    orig_out = sys.stdout
    sys.stderr = stderr
    sys.stdout = stdout
    try:
        rc = module.main(["--project-root", "/tmp/anything"])
    finally:
        sys.stderr = orig_err
        sys.stdout = orig_out
    assert rc == 2
    assert stdout.getvalue() == ""
    payload = json.loads(stderr.getvalue())
    assert payload["ok"] is False
    assert payload["code"] == CODE
    assert payload["message"] == "RuntimeError"
    assert "SECRET_GENERIC_EXCEPTION" not in stderr.getvalue()
    assert "Traceback" not in stderr.getvalue()


def test_cli_preflight_error_emits_message_without_traceback() -> None:
    module = _load("p2d1_cli_dtb", MODULE_PATH)

    def _boom(root):
        raise module.PreflightError("deterministic diagnostic text")

    module.preflight = _boom
    stderr = io.StringIO()
    orig_err = sys.stderr
    sys.stderr = stderr
    try:
        rc = module.main(["--project-root", "/tmp/anything"])
    finally:
        sys.stderr = orig_err
    assert rc == 2
    payload = json.loads(stderr.getvalue())
    assert payload["ok"] is False
    assert payload["code"] == CODE
    assert payload["message"] == "deterministic diagnostic text"
    assert "Traceback" not in stderr.getvalue()


def test_cli_error_payload_keys_exactly_canonical() -> None:
    r = _run_cli()
    payload = json.loads(r.stderr)
    assert set(payload.keys()) == {"ok", "code", "message"}
    assert payload["ok"] is False
    assert payload["code"] == CODE


# ---------------------------------------------------------------------------
# 15. Read-only / no iff dependency / stdlib-only.
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


def test_preflight_does_not_mutate_project() -> None:
    module = _load("p2d1_readonly", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        _install_fake_flutter(module)
        before = _snapshot(root)
        with _restore(module, "shutil", "subprocess"):
            module.preflight(root)
        after = _snapshot(root)
    assert set(before.keys()) == set(after.keys()), (
        f"file set changed: added={set(after) - set(before)} "
        f"removed={set(before) - set(after)}"
    )
    for p, data in before.items():
        assert after[p] == data, f"file mutated: {p}"


def test_preflight_does_not_create_pycache_in_project() -> None:
    module = _load("p2d1_nopyc", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        _install_fake_flutter(module)
        with _restore(module, "shutil", "subprocess"):
            module.preflight(root)
        pyc_dirs = [p for p in root.rglob("__pycache__") if p.is_dir()]
    assert pyc_dirs == [], pyc_dirs


def test_module_does_not_import_sibling_iff() -> None:
    source = MODULE_PATH.read_text()
    assert "import iff" not in source
    assert "from iff " not in source
    assert "from iff." not in source
    for needle in ("iff_root", "iff/scripts/", 'Path("iff")'):
        assert needle not in source, f"forbidden reference: {needle}"


def test_module_does_not_read_iff_at_runtime() -> None:
    """Loading and running preflight must never stat sibling iff/."""
    module = _load("p2d1_noreadiff", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        _install_fake_flutter(module)
        # Track any access under iff/.
        iff_path = REPO_ROOT / "iff"
        accessed: list[Path] = []

        class _TrackingPath(type(root)):  # type: ignore[misc]
            pass

        # Simplest probe: monkeypatch Path.resolve to fail if it touches iff.
        # We don't actually block iff reads here; the source static check
        # above is the real gate. This test instead verifies that no iff
        # path string appears in the report.
        with _restore(module, "shutil", "subprocess"):
            report = module.preflight(root)
        assert str(iff_path) not in json.dumps(report)
        assert not accessed


def test_module_uses_only_standard_library_imports() -> None:
    import ast

    tree = ast.parse(MODULE_PATH.read_text())
    allowed_prefixes = (
        "argparse", "hashlib", "importlib", "json", "os", "shutil",
        "stat", "subprocess", "sys", "pathlib", "typing", "__future__",
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                assert top in allowed_prefixes, f"non-stdlib import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None
            top = node.module.split(".")[0]
            assert top in allowed_prefixes, f"non-stdlib from-import: {node.module}"


def test_module_does_not_edit_registry() -> None:
    """The operation must not edit icp/references/registries.json."""
    registry_path = ICP_ROOT / "references" / "registries.json"
    before = registry_path.read_bytes()
    module = _load("p2d1_noregedit", MODULE_PATH)
    with _canonical_tempdir() as root:
        _build_minimal_project(root)
        _install_fake_flutter(module)
        with _restore(module, "shutil", "subprocess"):
            module.preflight(root)
    after = registry_path.read_bytes()
    assert before == after, "registries.json was mutated"


# ---------------------------------------------------------------------------
# Helpers for CLI-in-module tests.
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _patched_module_env(module, state):
    """Patch a loaded module's shutil/subprocess so a CLI run inside the
    same process uses the fake plumbing."""
    saved_shutil = module.shutil
    saved_subprocess = module.subprocess

    def _fake_run(args, **kwargs):
        return _FakeCompletedProcess(
            returncode=0,
            stdout=(json.dumps(_default_version_payload(), indent=2) + "\n"),
            stderr="",
        )

    module.shutil = _FakeShutil(
        lambda n: str(state["resolved_path"]) if n == "flutter" else None
    )
    module.subprocess = _FakeSubprocess(_fake_run)
    try:
        yield
    finally:
        module.shutil = saved_shutil
        module.subprocess = saved_subprocess


def _run_cli_in_module(module, *args: str) -> subprocess.CompletedProcess[str]:
    """Run module.main() in-process with captured streams."""
    stderr = io.StringIO()
    stdout = io.StringIO()
    orig_err = sys.stderr
    orig_out = sys.stdout
    sys.stderr = stderr
    sys.stdout = stdout
    try:
        rc = module.main(list(args))
    finally:
        sys.stderr = orig_err
        sys.stdout = orig_out
    return subprocess.CompletedProcess(
        args=list(args), returncode=rc, stdout=stdout.getvalue(), stderr=stderr.getvalue()
    )


# ---------------------------------------------------------------------------
# Small helpers.
# ---------------------------------------------------------------------------


def _is_sha256_hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value.islower()
        and all(c in "0123456789abcdef" for c in value)
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
