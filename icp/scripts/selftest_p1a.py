#!/usr/bin/env python3
"""Vertical RED -> GREEN selftest for ICP P1a.

Covers the strict JSON run-config resolver, immutable registries, read-only
fail-fast preflight surfaces, and the CLI contracts. Uses only the Python
standard library and temp fixtures. Run directly:

    python3 icp/scripts/selftest_p1a.py
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ICP_SCRIPTS = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Module loaders (file-path based; never imports iff).
# ---------------------------------------------------------------------------


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_COMMON = _load("icp_common", ICP_SCRIPTS / "icp_common.py")
_RESOLVE = _load("resolve_run_config", ICP_SCRIPTS / "resolve_run_config.py")
_PREFLIGHT = _load("preflight_selection", ICP_SCRIPTS / "preflight_selection.py")


def _registries() -> dict:
    return _COMMON.load_registries()


def _write_config(directory: Path, payload: dict | str, name: str = "config.json") -> Path:
    path = directory / name
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _run_resolve(config: Path, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ICP_SCRIPTS / "resolve_run_config.py"),
         "--config", str(config), "--cwd", str(cwd)],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def _run_preflight(config: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ICP_SCRIPTS / "preflight_selection.py"),
         "--config", str(config)],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def _err_payload(result: subprocess.CompletedProcess[str]) -> dict:
    assert result.stderr.strip(), "expected JSON failure on stderr, got empty"
    return json.loads(result.stderr)


def _ok_payload(result: subprocess.CompletedProcess[str]) -> dict:
    return json.loads(result.stdout)


def _valid_base_config(**overrides) -> dict:
    base = {
        "task_source": "csv",
        "task_ref": "tasks.csv",
        "design_source": "lanhu-figma",
        "platform": "flutter",
        "project_root": ".",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. duplicate / unknown / missing / wrong-type config failures
# ---------------------------------------------------------------------------


def test_non_object_root_array_invalid_input() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _write_config(d, '[1,2,3]')
        r = _run_resolve(cfg, d)
        assert r.returncode != 0
        payload = _err_payload(r)
        assert payload["ok"] is False
        assert payload["code"] == _COMMON.INVALID_INPUT


def test_non_object_root_scalar_invalid_input() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _write_config(d, '"just-a-string"')
        r = _run_resolve(cfg, d)
        assert r.returncode != 0
        assert _err_payload(r)["code"] == _COMMON.INVALID_INPUT


def test_duplicate_json_key_invalid_input() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _write_config(d,
            '{"platform": "flutter", "platform": "vue", '
            '"task_source":"csv","task_ref":"t.csv",'
            '"design_source":"lanhu-figma","project_root":"."}')
        r = _run_resolve(cfg, d)
        assert r.returncode != 0
        payload = _err_payload(r)
        assert payload["code"] == _COMMON.INVALID_INPUT
        assert "duplicate" in payload["message"]


def test_missing_required_key_invalid_input() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        bad = _valid_base_config()
        del bad["design_source"]
        cfg = _write_config(d, bad)
        r = _run_resolve(cfg, d)
        assert r.returncode != 0
        payload = _err_payload(r)
        assert payload["code"] == _COMMON.INVALID_INPUT
        assert "design_source" in payload["message"]


def test_unknown_key_invalid_input() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        bad = _valid_base_config(extra_key="nope")
        cfg = _write_config(d, bad)
        r = _run_resolve(cfg, d)
        assert r.returncode != 0
        payload = _err_payload(r)
        assert payload["code"] == _COMMON.INVALID_INPUT
        assert "extra_key" in payload["message"]


def test_non_string_value_invalid_input() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        bad = _valid_base_config(platform=123)
        cfg = _write_config(d, bad)
        r = _run_resolve(cfg, d)
        assert _err_payload(r)["code"] == _COMMON.INVALID_INPUT


def test_empty_string_value_invalid_input() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        bad = _valid_base_config(platform="")
        cfg = _write_config(d, bad)
        r = _run_resolve(cfg, d)
        assert _err_payload(r)["code"] == _COMMON.INVALID_INPUT


def test_profile_non_string_invalid_input() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        bad = _valid_base_config(profile=["flutter-standard"])
        cfg = _write_config(d, bad)
        r = _run_resolve(cfg, d)
        assert _err_payload(r)["code"] == _COMMON.INVALID_INPUT


def test_profile_empty_string_invalid_input() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        bad = _valid_base_config(profile="")
        cfg = _write_config(d, bad)
        r = _run_resolve(cfg, d)
        assert _err_payload(r)["code"] == _COMMON.INVALID_INPUT


# ---------------------------------------------------------------------------
# 2. config keys attempting command/script/env/prompt/registry overrides fail
# ---------------------------------------------------------------------------


def test_rejects_command_key() -> None:
    for evil in ("command", "cmd", "shell", "script", "script_path", "env",
                 "env_var", "prompt", "system_prompt", "registry_path",
                 "registry", "operations", "executable", "argv", "subprocess"):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            bad = _valid_base_config()
            bad[evil] = "rm -rf /"
            cfg = _write_config(d, bad)
            r = _run_resolve(cfg, d)
            assert r.returncode != 0, f"accepted evil key {evil!r}"
            payload = _err_payload(r)
            assert payload["code"] == _COMMON.INVALID_INPUT, evil


def test_rejects_operation_id_key() -> None:
    """Operation IDs (visible_codegen etc.) must not be accepted as config keys."""
    ops = [op["id"] for op in _registries()["operations"]]
    for op_id in ops:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            bad = _valid_base_config()
            bad[op_id] = "arbitrary"
            cfg = _write_config(d, bad)
            r = _run_resolve(cfg, d)
            assert r.returncode != 0, f"accepted operation-id key {op_id!r}"
            assert _err_payload(r)["code"] == _COMMON.INVALID_INPUT


# ---------------------------------------------------------------------------
# 3. ID / profile values cannot escape exact allowlists
# ---------------------------------------------------------------------------


def test_unknown_task_source_unsupported_task_source() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _write_config(d, _valid_base_config(task_source="sqlite"))
        r = _run_resolve(cfg, d)
        payload = _err_payload(r)
        assert payload["code"] == _COMMON.UNSUPPORTED_TASK_SOURCE


def test_unknown_design_source_unsupported_design_source() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _write_config(d, _valid_base_config(design_source=" sketch"))
        r = _run_resolve(cfg, d)
        payload = _err_payload(r)
        assert payload["code"] == _COMMON.UNSUPPORTED_DESIGN_SOURCE


def test_unknown_platform_unsupported_platform() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _write_config(d, _valid_base_config(platform="react-native"))
        r = _run_resolve(cfg, d)
        payload = _err_payload(r)
        assert payload["code"] == _COMMON.UNSUPPORTED_PLATFORM


def test_unknown_profile_unsupported_profile() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _write_config(d, _valid_base_config(profile="flutter-deluxe"))
        r = _run_resolve(cfg, d)
        payload = _err_payload(r)
        assert payload["code"] == _COMMON.UNSUPPORTED_PROFILE


def test_id_cannot_escape_with_whitespace_or_case() -> None:
    """Allowlists are exact; surrounding whitespace or case-tweaks must fail."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        for evil, field in [("csv ", "task_source"), ("CSV", "task_source"),
                            (" lanhu-figma", "design_source"),
                            ("Lanhu-Figma", "design_source"),
                            ("Flutter", "platform"),
                            (" flutter", "platform")]:
            bad = _valid_base_config()
            bad[field] = evil
            cfg = _write_config(d, bad, name=f"{field}_{evil}.json")
            r = _run_resolve(cfg, d)
            assert r.returncode != 0, f"accepted {field}={evil!r}"


# ---------------------------------------------------------------------------
# 4. relative path canonicalization uses explicit --cwd
# ---------------------------------------------------------------------------


def test_task_ref_canonicalized_against_cwd() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        sub = d / "proj"
        sub.mkdir()
        (sub / "tasks.csv").write_text("status,design_url\n", encoding="utf-8")
        cfg = _write_config(d, _valid_base_config(task_ref="tasks.csv", project_root="."), name="c.json")
        r = _run_resolve(cfg, sub)
        assert r.returncode == 0, r.stderr
        out = _ok_payload(r)
        assert out["task_ref"] == str((sub / "tasks.csv").resolve())
        assert out["project_root"] == str(sub.resolve())


def test_project_root_dotdot_canonicalized() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        nested = d / "a" / "b"
        nested.mkdir(parents=True)
        cfg = _write_config(d, _valid_base_config(project_root="..", task_ref="t.csv"))
        r = _run_resolve(cfg, nested)
        assert r.returncode == 0, r.stderr
        out = _ok_payload(r)
        assert out["project_root"] == str((nested / "..").resolve())


def test_task_ref_with_shell_chars_is_inert_path() -> None:
    """Shell-looking chars in a legitimate path remain inert, never executed."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        weird = "t; rm -rf / & echo hi | $(whoami).csv"
        bad = _valid_base_config(task_ref=weird)
        cfg = _write_config(d, bad)
        r = _run_resolve(cfg, d)
        assert r.returncode == 0, r.stderr
        out = _ok_payload(r)
        assert out["task_ref"] == str((d / weird).resolve())


# ---------------------------------------------------------------------------
# 4b. resolved paths preserve final-component symlink identity (review fix)
# ---------------------------------------------------------------------------


def test_resolved_task_ref_symlink_preserved_and_rejected_by_preflight() -> None:
    """A task_ref that is a symlink must survive resolution so the direct
    preflight symlink gate rejects it (instead of silently accepting the
    target after Path.resolve() dereferenced the final component)."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        real = d / "real.csv"
        real.write_bytes(_good_csv())
        link = d / "link.csv"
        link.symlink_to(real)
        cfg = _write_config(
            d, _valid_base_config(task_ref="link.csv", project_root=".")
        )
        r = _run_resolve(cfg, d)
        assert r.returncode == 0, r.stderr
        resolved = _ok_payload(r)
        # Final component identity preserved: still names the symlink on disk.
        assert Path(resolved["task_ref"]).name == "link.csv"
        assert Path(resolved["task_ref"]).is_symlink()
        # The direct preflight must reject it as a symlink.
        result = _PREFLIGHT.preflight_csv_task_source(resolved["task_ref"])
        assert result.ok is False
        assert result.code == _COMMON.TASK_PREFLIGHT_FAILED
        assert "symlink" in result.message.lower()
        # Real target bytes unchanged.
        assert real.read_bytes() == _good_csv()


def test_resolved_project_root_symlink_preserved_and_rejected_by_preflight() -> None:
    """A project_root that is a symlink must survive resolution so the direct
    preflight symlink gate rejects it."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        real = d / "real_root"
        real.mkdir()
        link = d / "link_root"
        link.symlink_to(real)
        cfg = _write_config(d, _valid_base_config(project_root="link_root"))
        r = _run_resolve(cfg, d)
        assert r.returncode == 0, r.stderr
        resolved = _ok_payload(r)
        assert Path(resolved["project_root"]).name == "link_root"
        assert Path(resolved["project_root"]).is_symlink()
        result = _PREFLIGHT.preflight_project_root(resolved["project_root"])
        assert result.ok is False
        assert result.code == _COMMON.PROJECT_PREFLIGHT_FAILED
        assert "symlink" in result.message.lower()


# ---------------------------------------------------------------------------
# 5. defaults resolve only for Flutter/Vue; mismatched profile fails
# ---------------------------------------------------------------------------


def test_flutter_default_profile_resolved() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _write_config(d, _valid_base_config(platform="flutter"))
        r = _run_resolve(cfg, d)
        assert r.returncode == 0, r.stderr
        assert _ok_payload(r)["profile"] == "flutter-standard"


def test_vue_default_profile_resolved() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _write_config(d, _valid_base_config(platform="vue"))
        r = _run_resolve(cfg, d)
        assert r.returncode == 0, r.stderr
        assert _ok_payload(r)["profile"] == "vue-vite"


def test_nextjs_default_profile_resolved() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _write_config(d, _valid_base_config(platform="nextjs"))
        r = _run_resolve(cfg, d)
        assert r.returncode == 0, r.stderr
        assert _ok_payload(r)["profile"] == "nextjs-standard"


def test_flutter_explicit_default_profile_ok() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _write_config(d, _valid_base_config(platform="flutter", profile="flutter-standard"))
        r = _run_resolve(cfg, d)
        assert r.returncode == 0, r.stderr
        assert _ok_payload(r)["profile"] == "flutter-standard"


def test_flutter_mismatched_profile_unsupported_profile() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _write_config(d, _valid_base_config(platform="flutter", profile="vue-vite"))
        r = _run_resolve(cfg, d)
        payload = _err_payload(r)
        assert payload["code"] == _COMMON.UNSUPPORTED_PROFILE


def test_nextjs_any_profile_unsupported_profile() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _write_config(d, _valid_base_config(platform="nextjs", profile="anything"))
        r = _run_resolve(cfg, d)
        payload = _err_payload(r)
        assert payload["code"] == _COMMON.UNSUPPORTED_PROFILE


# ---------------------------------------------------------------------------
# 6. all seven registered-but-unimplemented platforms return unsupported_platform
#    before TaskSource access and without task-byte change
# ---------------------------------------------------------------------------


SEVEN_PLATFORMS = [
    "flutter", "vue", "nextjs", "ios-swift", "ios-objc",
    "android-java", "android-kotlin",
]


def test_all_seven_platforms_supported_in_preflight() -> None:
    for platform in SEVEN_PLATFORMS:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            cfg = _write_config(d, _valid_base_config(platform=platform))
            resolve_r = _run_resolve(cfg, d)
            assert resolve_r.returncode == 0, resolve_r.stderr
            pf = _run_preflight(cfg)
            assert pf.returncode == 0, f"preflight failed for {platform}: {pf.stderr}"
            assert _ok_payload(pf)["details"]["platform"] == platform


def test_unsupported_platform_before_task_access() -> None:
    """A nonexistent/unreadable task path must NOT replace unsupported_platform."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        # task_ref points at a path that does NOT exist anywhere.
        bad = _valid_base_config(platform="react-native", task_ref="does-not-exist.csv")
        cfg = _write_config(d, bad)
        resolve_r = _run_resolve(cfg, d)
        assert resolve_r.returncode != 0
        payload = _err_payload(resolve_r)
        assert payload["code"] == _COMMON.UNSUPPORTED_PLATFORM


def test_task_bytes_unchanged_after_unsupported_platform() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        csv_path = d / "tasks.csv"
        original = b"status,design_url\ndone,https://figma.com/file/x\n"
        csv_path.write_bytes(original)
        cfg = _write_config(d, _valid_base_config(platform="react-native", task_ref="tasks.csv"))
        resolve_r = _run_resolve(cfg, d)
        assert _err_payload(resolve_r)["code"] == _COMMON.UNSUPPORTED_PLATFORM
        assert csv_path.read_bytes() == original


# ---------------------------------------------------------------------------
# 7. unknown task/design source error codes (CLI level)
# ---------------------------------------------------------------------------


def test_unknown_task_source_cli() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _write_config(d, _valid_base_config(task_source="excel"))
        r = _run_resolve(cfg, d)
        assert _err_payload(r)["code"] == _COMMON.UNSUPPORTED_TASK_SOURCE


def test_unknown_design_source_cli() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _write_config(d, _valid_base_config(design_source="figma-only"))
        r = _run_resolve(cfg, d)
        assert _err_payload(r)["code"] == _COMMON.UNSUPPORTED_DESIGN_SOURCE


# ---------------------------------------------------------------------------
# 8. .xlsx / CSV symlink / non-regular / malformed/missing headers / invalid
#    statuses fail with task bytes unchanged
# ---------------------------------------------------------------------------


def _good_csv() -> bytes:
    return b"status,design_url\ndone,https://figma.com/file/abc\n,https://lanhuapp.com/url/x\ndoing,https://figma.com/proto/z\n"


def test_xlsx_unsupported_task_format() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        p = d / "tasks.xlsx"
        p.write_bytes(b"PK\x03\x04 not really xlsx")
        result = _PREFLIGHT.preflight_csv_task_source(p)
        assert result.ok is False
        assert result.code == _COMMON.UNSUPPORTED_TASK_FORMAT
        assert p.read_bytes() == b"PK\x03\x04 not really xlsx"


def test_non_csv_suffix_unsupported_task_format() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        p = d / "tasks.txt"
        p.write_bytes(b"status,design_url\n")
        result = _PREFLIGHT.preflight_csv_task_source(p)
        assert result.ok is False
        assert result.code == _COMMON.UNSUPPORTED_TASK_FORMAT


def test_csv_symlink_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        real = d / "real.csv"
        real.write_bytes(_good_csv())
        link = d / "link.csv"
        link.symlink_to(real)
        result = _PREFLIGHT.preflight_csv_task_source(link)
        assert result.ok is False
        assert result.code == _COMMON.TASK_PREFLIGHT_FAILED
        assert "symlink" in result.message.lower()
        assert real.read_bytes() == _good_csv()


def test_non_regular_csv_rejected() -> None:
    if os.name != "posix":
        return
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        # A FIFO is not a regular file.
        fifo = d / "pipe.csv"
        try:
            os.mkfifo(fifo)
        except (OSError, PermissionError):
            return
        result = _PREFLIGHT.preflight_csv_task_source(fifo)
        assert result.ok is False
        assert result.code == _COMMON.TASK_PREFLIGHT_FAILED


def test_missing_csv_file_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        result = _PREFLIGHT.preflight_csv_task_source(d / "absent.csv")
        assert result.ok is False
        assert result.code == _COMMON.TASK_PREFLIGHT_FAILED


def test_malformed_csv_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        p = d / "tasks.csv"
        # Unterminated quoted field.
        original = b'status,design_url\n"x,https://figma.com/file/y\n'
        p.write_bytes(original)
        result = _PREFLIGHT.preflight_csv_task_source(p)
        assert result.ok is False
        assert result.code == _COMMON.TASK_PREFLIGHT_FAILED
        assert p.read_bytes() == original


def test_csv_duplicate_status_header_rejected() -> None:
    """Structurally strict CSV: duplicate canonical status header is rejected."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        p = d / "tasks.csv"
        original = b"status,design_url,status\n,https://figma.com/file/a,done\n"
        p.write_bytes(original)
        result = _PREFLIGHT.preflight_csv_task_source(p)
        assert result.ok is False
        assert result.code == _COMMON.TASK_PREFLIGHT_FAILED
        assert "status" in result.message
        assert p.read_bytes() == original


def test_csv_duplicate_design_url_header_rejected() -> None:
    """Structurally strict CSV: duplicate canonical design_url header rejected."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        p = d / "tasks.csv"
        original = b"status,design_url,design_url\n,,https://figma.com/file/a\n"
        p.write_bytes(original)
        result = _PREFLIGHT.preflight_csv_task_source(p)
        assert result.ok is False
        assert result.code == _COMMON.TASK_PREFLIGHT_FAILED
        assert "design_url" in result.message
        assert p.read_bytes() == original


def test_csv_unclosed_quote_rejected() -> None:
    """Structurally strict CSV: an unclosed quoted field is rejected via the
    standard library parser in ``strict`` mode (``csv.Error: unexpected end of
    data``), surfaced deterministically as ``task_preflight_failed``."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        p = d / "tasks.csv"
        original = b'status,design_url\n"x,https://figma.com/file/y\n'
        p.write_bytes(original)
        result = _PREFLIGHT.preflight_csv_task_source(p)
        assert result.ok is False
        assert result.code == _COMMON.TASK_PREFLIGHT_FAILED
        assert "end of data" in result.message.lower() or "quote" in result.message.lower()
        assert p.read_bytes() == original


def test_csv_valid_multiline_quoted_field_accepted() -> None:
    """RFC 4180 allows embedded newlines inside a quoted field. The standard
    library CSV parser must accept such a record as one logical row; P1a must
    not invent a no-multiline policy that the approved contract does not have.
    """
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        p = d / "tasks.csv"
        original = (
            b'status,design_url\n'
            b'done,"https://figma.com/file/abc\n  continuation line"\n'
        )
        p.write_bytes(original)
        result = _PREFLIGHT.preflight_csv_task_source(p)
        assert result.ok is True, result.message
        assert p.read_bytes() == original
        assert result.details["rows"] == 1


def test_csv_unreadable_file_returns_preflight_failure() -> None:
    """I/O failures at the task preflight boundary must become deterministic
    PreflightResult failures, never uncaught exceptions or tracebacks."""
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return  # root bypasses read permission; not stable on macOS as root.
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        p = d / "tasks.csv"
        p.write_bytes(_good_csv())
        p.chmod(0o000)
        try:
            result = _PREFLIGHT.preflight_csv_task_source(p)
            assert result.ok is False
            assert result.code == _COMMON.TASK_PREFLIGHT_FAILED
        finally:
            p.chmod(0o600)


def test_missing_header_design_url_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        p = d / "tasks.csv"
        original = b"status\n,done\n"
        p.write_bytes(original)
        result = _PREFLIGHT.preflight_csv_task_source(p)
        assert result.ok is False
        assert result.code == _COMMON.TASK_PREFLIGHT_FAILED
        assert "design_url" in result.message
        assert p.read_bytes() == original


def test_missing_header_status_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        p = d / "tasks.csv"
        original = b"design_url\nhttps://figma.com/file/a\n"
        p.write_bytes(original)
        result = _PREFLIGHT.preflight_csv_task_source(p)
        assert result.ok is False
        assert result.code == _COMMON.TASK_PREFLIGHT_FAILED
        assert "status" in result.message


def test_alias_header_rejected_in_p1a() -> None:
    """P1a uses exact canonical headers; P2 owns aliases."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        p = d / "tasks.csv"
        # 状态 / 设计稿地址 are aliases used by iff; P1a must reject them.
        original = "状态,设计稿地址\ndone,https://figma.com/file/a\n".encode("utf-8")
        p.write_bytes(original)
        result = _PREFLIGHT.preflight_csv_task_source(p)
        assert result.ok is False
        assert result.code == _COMMON.TASK_PREFLIGHT_FAILED


def test_invalid_status_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        p = d / "tasks.csv"
        original = b"status,design_url\npending,https://figma.com/file/a\n"
        p.write_bytes(original)
        result = _PREFLIGHT.preflight_csv_task_source(p)
        assert result.ok is False
        assert result.code == _COMMON.TASK_PREFLIGHT_FAILED
        assert "status" in result.message.lower() or "pending" in result.message
        assert p.read_bytes() == original


def test_all_valid_statuses_pass() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        p = d / "tasks.csv"
        original = (
            b"status,design_url\n"
            b",https://figma.com/file/empty\n"
            b"doing,https://figma.com/file/doing\n"
            b"done,https://figma.com/file/done\n"
            b"error,https://figma.com/file/error\n"
        )
        p.write_bytes(original)
        result = _PREFLIGHT.preflight_csv_task_source(p)
        assert result.ok is True, result.message
        assert p.read_bytes() == original


# ---------------------------------------------------------------------------
# 9. CSV probe/lock success leaves identical bytes and no probe file
# ---------------------------------------------------------------------------


def test_csv_preflight_success_no_mutation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        p = d / "tasks.csv"
        original = _good_csv()
        p.write_bytes(original)
        before_stat = p.stat().st_mtime_ns
        result = _PREFLIGHT.preflight_csv_task_source(p)
        assert result.ok is True, result.message
        assert p.read_bytes() == original
        assert result.details["sha256"] == _COMMON.sha256_hex(original)


def test_csv_preflight_success_no_probe_file_left() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        p = d / "tasks.csv"
        p.write_bytes(_good_csv())
        _PREFLIGHT.preflight_csv_task_source(p)
        leftovers = [child.name for child in d.iterdir() if "probe" in child.name.lower()]
        assert leftovers == [], f"probe files left behind: {leftovers}"
        assert list(d.iterdir()) == [p]


def test_csv_preflight_succeeds_with_unrelated_probe_named_file() -> None:
    """The atomic-probe cleanup must only reason about the exact temporary
    paths it owns; a pre-existing file like ``customer_probe_data.txt`` must
    not cause a false failure."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        p = d / "tasks.csv"
        original = _good_csv()
        p.write_bytes(original)
        unrelated = d / "customer_probe_data.txt"
        unrelated_payload = b"important customer data"
        unrelated.write_bytes(unrelated_payload)
        result = _PREFLIGHT.preflight_csv_task_source(p)
        assert result.ok is True, result.message
        assert p.read_bytes() == original
        assert unrelated.read_bytes() == unrelated_payload
        assert unrelated.exists()
        # No invocation-owned probe files remain.
        icp_probes = [
            child.name for child in d.iterdir() if child.name.startswith(".icp-probe-")
        ]
        assert icp_probes == []


# ---------------------------------------------------------------------------
# 10. design locator + project-root preflight read-only and fail visibly
# ---------------------------------------------------------------------------


def test_design_locator_empty_rejected() -> None:
    result = _PREFLIGHT.preflight_design_locator("")
    assert result.ok is False
    assert result.code == _COMMON.DESIGN_PREFLIGHT_FAILED


def test_design_locator_non_string_rejected() -> None:
    result = _PREFLIGHT.preflight_design_locator(None)  # type: ignore[arg-type]
    assert result.ok is False
    assert result.code == _COMMON.DESIGN_PREFLIGHT_FAILED


def test_design_locator_malformed_rejected() -> None:
    for bad in ["not-a-url", "ftp://figma.com/x", "https://evil.com/x",
                "https://figma.com", "http:/figma.com/file/x", "  https://figma.com/x"]:
        result = _PREFLIGHT.preflight_design_locator(bad)
        assert result.ok is False, f"accepted malformed {bad!r}"
        assert result.code == _COMMON.DESIGN_PREFLIGHT_FAILED


def test_design_locator_valid_lanhu_and_figma_pass() -> None:
    for good in [
        "https://lanhuapp.com/url/abc-def",
        "https://figma.com/file/abc/Name",
        "https://www.figma.com/proto/x/y?node=1",
        "https://lanhuapp.com/web/#/item/project/board?pid=1",
    ]:
        result = _PREFLIGHT.preflight_design_locator(good)
        assert result.ok is True, f"rejected good locator {good!r}: {result.message}"


def test_project_root_missing_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        result = _PREFLIGHT.preflight_project_root(Path(tmp) / "missing")
        assert result.ok is False
        assert result.code == _COMMON.PROJECT_PREFLIGHT_FAILED


def test_project_root_not_directory_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        f = d / "file"
        f.write_bytes(b"x")
        result = _PREFLIGHT.preflight_project_root(f)
        assert result.ok is False
        assert result.code == _COMMON.PROJECT_PREFLIGHT_FAILED


def test_project_root_symlink_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        real = d / "real"
        real.mkdir()
        link = d / "link"
        link.symlink_to(real)
        result = _PREFLIGHT.preflight_project_root(link)
        assert result.ok is False
        assert result.code == _COMMON.PROJECT_PREFLIGHT_FAILED
        assert "symlink" in result.message.lower()


def test_project_root_read_only_no_mutation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        marker = d / "marker.txt"
        marker.write_bytes(b"keep-me")
        result = _PREFLIGHT.preflight_project_root(d)
        assert result.ok is True, result.message
        # Nothing was added or removed.
        assert marker.read_bytes() == b"keep-me"
        assert sorted(p.name for p in d.iterdir()) == ["marker.txt"]


# ---------------------------------------------------------------------------
# 11. registry shape: 7 platforms, 9 operations, allowed cap states, no exec fields
# ---------------------------------------------------------------------------


def test_registry_seven_platform_ids_exact() -> None:
    reg = _registries()
    assert list(reg["platforms"].keys()) == SEVEN_PLATFORMS


def test_registry_nine_operations_exact() -> None:
    reg = _registries()
    ids = [op["id"] for op in reg["operations"]]
    assert ids == [
        "project_preflight", "visible_codegen", "fixture_codegen", "trace_harness",
        "packaging", "test_runner", "runtime_capture", "project_gates", "fan_in",
    ]


def test_registry_capability_states_allowed_only() -> None:
    reg = _registries()
    allowed = set(reg["capability_states"])
    assert allowed == {"required", "optional-with-shared-policy", "unsupported"}
    for op_id, state in reg["capabilities"].items():
        assert state in allowed, f"bad cap state {state!r} for {op_id}"


def test_registry_operations_have_no_executable_fields() -> None:
    reg = _registries()
    forbidden = {"command", "cmd", "shell", "script", "script_path", "exec",
                 "executable", "argv", "env", "module", "import"}
    for op in reg["operations"]:
        assert set(op.keys()) == {"id"}, f"unexpected op fields: {op}"
        assert op["id"] not in forbidden


def test_registry_task_and_design_sources_exact() -> None:
    reg = _registries()
    assert reg["task_sources"] == ["csv"]
    assert reg["design_sources"] == ["lanhu-figma"]


def test_registry_all_platforms_marked_activated() -> None:
    reg = _registries()
    for name, entry in reg["platforms"].items():
        assert entry.get("activated") is True, f"{name} not activated"


def test_registry_defaults_match_profiles() -> None:
    reg = _registries()
    assert reg["platforms"]["flutter"]["default_profile"] == "flutter-standard"
    assert reg["platforms"]["vue"]["default_profile"] == "vue-vite"
    assert reg["platforms"]["nextjs"]["default_profile"] == "nextjs-standard"
    assert reg["platforms"]["ios-swift"]["default_profile"] == "ios-swift-standard"
    assert reg["platforms"]["ios-objc"]["default_profile"] == "ios-objc-standard"
    assert reg["platforms"]["android-java"]["default_profile"] == "android-java-standard"
    assert reg["platforms"]["android-kotlin"]["default_profile"] == "android-kotlin-standard"


def test_load_registries_signature_takes_no_path() -> None:
    """The production registry loader must not accept an external override path."""
    sig = inspect.signature(_COMMON.load_registries)
    assert list(sig.parameters) == [], (
        f"load_registries must take no parameters; got {sig}"
    )


def test_load_registries_rejects_path_kwarg() -> None:
    """Even if a caller tries to inject a path, it must raise rather than load
    a different registry."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        evil = d / "evil.json"
        evil.write_text('{"platforms": {"x": {"activated": true}}}', encoding="utf-8")
        try:
            _COMMON.load_registries(path=evil)  # type: ignore[call-arg]
        except TypeError:
            pass
        else:
            raise AssertionError("load_registries accepted a path= override")
    reg = _COMMON.load_registries()
    assert "platforms" in reg
    assert "x" not in reg["platforms"]


# ---------------------------------------------------------------------------
# CLI surface checks: success -> canonical stdout; failure -> one stderr JSON
# ---------------------------------------------------------------------------


def test_resolve_cli_success_canonical_json() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _write_config(d, _valid_base_config())
        r = _run_resolve(cfg, d)
        assert r.returncode == 0, r.stderr
        assert r.stderr == ""
        out = _ok_payload(r)
        # Canonical: sorted keys, two-space indent, trailing newline.
        assert r.stdout == _COMMON.canonical_json_bytes(out).decode("utf-8")
        assert set(out.keys()) == {
            "task_source", "task_ref", "design_source",
            "platform", "profile", "project_root",
        }


def test_resolve_cli_failure_one_stderr_json_no_traceback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _write_config(d, _valid_base_config(platform="nope"))
        r = _run_resolve(cfg, d)
        assert r.returncode != 0
        assert r.stdout == ""
        assert "Traceback" not in r.stderr
        # Exactly one JSON object on stderr (canonical, pretty-printed).
        payload = json.loads(r.stderr)
        assert set(payload.keys()) == {"ok", "code", "message"}
        assert payload["ok"] is False
        assert payload["code"] == _COMMON.UNSUPPORTED_PLATFORM


def test_preflight_cli_failure_uses_stderr_json() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _write_config(d, _valid_base_config(platform="react-native"))
        r = _run_preflight(cfg)
        assert r.returncode != 0
        assert r.stdout == ""
        payload = json.loads(r.stderr)
        assert payload["ok"] is False
        assert payload["code"] == _COMMON.UNSUPPORTED_PLATFORM


# ---------------------------------------------------------------------------
# Preflight CLI strict config decode: never traceback (review fix)
# ---------------------------------------------------------------------------


def test_preflight_cli_array_root_no_traceback() -> None:
    """An array root must surface as invalid_input, not a .get() traceback."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _write_config(d, "[1,2,3]", name="arr.json")
        r = _run_preflight(cfg)
        assert r.returncode != 0
        assert r.stdout == ""
        assert "Traceback" not in r.stderr
        payload = json.loads(r.stderr)
        assert payload["ok"] is False
        assert payload["code"] == _COMMON.INVALID_INPUT


def test_preflight_cli_scalar_root_no_traceback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _write_config(d, '"a-string"', name="scalar.json")
        r = _run_preflight(cfg)
        assert r.returncode != 0
        assert "Traceback" not in r.stderr
        assert json.loads(r.stderr)["code"] == _COMMON.INVALID_INPUT


def test_preflight_cli_malformed_json_no_traceback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _write_config(d, "{not json", name="bad.json")
        r = _run_preflight(cfg)
        assert r.returncode != 0
        assert "Traceback" not in r.stderr
        assert json.loads(r.stderr)["code"] == _COMMON.INVALID_INPUT


def test_preflight_cli_duplicate_keys_no_traceback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _write_config(
            d, '{"platform":"flutter","platform":"vue"}', name="dup.json"
        )
        r = _run_preflight(cfg)
        assert r.returncode != 0
        assert "Traceback" not in r.stderr
        assert json.loads(r.stderr)["code"] == _COMMON.INVALID_INPUT


def test_preflight_cli_non_utf8_no_traceback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = d / "bin.json"
        cfg.write_bytes(b"\xff\xfe\x00bad")
        r = _run_preflight(cfg)
        assert r.returncode != 0
        assert "Traceback" not in r.stderr
        assert json.loads(r.stderr)["code"] == _COMMON.INVALID_INPUT


def test_preflight_cli_missing_required_field_no_traceback() -> None:
    """A resolved config missing required fields must fail with invalid_input."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _write_config(d, {"platform": "flutter"}, name="incomplete.json")
        r = _run_preflight(cfg)
        assert r.returncode != 0
        assert "Traceback" not in r.stderr
        assert json.loads(r.stderr)["code"] == _COMMON.INVALID_INPUT


def test_preflight_cli_unexpected_field_no_traceback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _write_config(
            d, {**_valid_base_config(), "rogue": "x"}, name="extra.json"
        )
        r = _run_preflight(cfg)
        assert r.returncode != 0
        assert "Traceback" not in r.stderr
        assert json.loads(r.stderr)["code"] == _COMMON.INVALID_INPUT


def test_preflight_cli_does_not_accept_registry_path_override() -> None:
    """The preflight CLI must not expose any registry-path input."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _write_config(d, _valid_base_config(), name="ok.json")
        evil = d / "evil.json"
        evil.write_text('{"platforms": {}}', encoding="utf-8")
        r = subprocess.run(
            [
                sys.executable,
                str(ICP_SCRIPTS / "preflight_selection.py"),
                "--config",
                str(cfg),
                "--registry",
                str(evil),
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        # argparse rejects the unknown --registry flag with exit code 2.
        assert r.returncode == 2
        assert "unrecognized" in r.stderr.lower() or "registry" in r.stderr.lower()


# ---------------------------------------------------------------------------
# Selftest runner
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
