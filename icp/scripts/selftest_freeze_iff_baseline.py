#!/usr/bin/env python3
"""Vertical RED→GREEN selftest for icp/scripts/freeze_iff_baseline.py.

Run directly:
    python3 icp/scripts/selftest_freeze_iff_baseline.py

Each ``test_*`` function exercises one observable behaviour of the public
freezer CLI / module API against either the live ``iff`` skill (read-only) or
an isolated synthetic fixture built in a private temp dir.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
IFF_ROOT = REPO_ROOT / "iff"
FREEZE_PATH = REPO_ROOT / "icp" / "scripts" / "freeze_iff_baseline.py"


def _load_freeze():
    spec = importlib.util.spec_from_file_location(
        "freeze_iff_baseline", str(FREEZE_PATH)
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["freeze_iff_baseline"] = module
    spec.loader.exec_module(module)
    return module


def _build_minimal_iff(root: Path, required: list[str], extra: list[str] | None = None) -> Path:
    """Create a tiny self-contained iff fixture the verifier accepts."""
    iff = root / "iff"
    scripts = iff / "scripts"
    scripts.mkdir(parents=True)
    skill_md = iff / "SKILL.md"
    skill_md.write_text(
        "---\nname: iff\ndescription: minimal fixture skill\n---\n\n# iff fixture\n",
        encoding="utf-8",
    )
    # Minimal validate_skill_structure mirroring the real contract surface used
    # by verify_pipeline_scripts (only what the verifier imports).
    (scripts / "validate_skill_structure.py").write_text(
        "def validate_skill(skill_dir):\n    return []\n",
        encoding="utf-8",
    )
    names = list(required) + list(extra or [])
    for name in names:
        if name in {"validate_skill_structure.py", "verify_pipeline_scripts.py"}:
            continue
        (scripts / name).write_text(f"# minimal {name}\n", encoding="utf-8")
    quoted = ", ".join('"' + n + '"' for n in required)
    required_literal = "[" + quoted + "]"
    (scripts / "verify_pipeline_scripts.py").write_text(
        "import argparse\n"
        "from pathlib import Path\n"
        "import sys\n"
        "from validate_skill_structure import validate_skill\n"
        f"REQUIRED = {required_literal}\n"
        "def main():\n"
        "    p = argparse.ArgumentParser()\n"
        "    p.add_argument('--skill-dir', default=str(Path(__file__).resolve().parents[1]))\n"
        "    args = p.parse_args()\n"
        "    skill = Path(args.skill_dir).resolve()\n"
        "    sd = skill / 'scripts'\n"
        "    missing = [n for n in REQUIRED if not (sd / n).is_file()]\n"
        "    if missing:\n"
        "        print('missing', missing, file=sys.stderr)\n"
        "        return 1\n"
        "    errs = validate_skill(skill)\n"
        "    if errs:\n"
        "        print(errs, file=sys.stderr)\n"
        "        return 1\n"
        "    print(f'ok {len(REQUIRED)} scripts in {sd}')\n"
        "    return 0\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit(main())\n",
        encoding="utf-8",
    )
    return iff


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(FREEZE_PATH), *args],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def test_parse_required_live_iff() -> None:
    freeze = _load_freeze()
    entries = freeze.parse_required_registry(IFF_ROOT / "scripts" / "verify_pipeline_scripts.py")
    assert len(entries) == 111, f"expected 111 REQUIRED entries, got {len(entries)}"
    first = entries[0]
    assert first["name"] == "classify_design.py"
    assert first["evidence"] == "iff/scripts/verify_pipeline_scripts.py:14"


def test_enumerate_live_iff() -> None:
    freeze = _load_freeze()
    scripts = freeze.enumerate_scripts(IFF_ROOT)
    live_files = sorted(p.name for p in (IFF_ROOT / "scripts").glob("*.py"))
    assert len(scripts) == len(live_files) == 165, (
        f"expected 165 live scripts, got snapshot={len(scripts)} live={len(live_files)}"
    )
    assert scripts[0]["path"] == f"iff/scripts/{live_files[0]}"
    # sha256 is 64 hex chars and stable across two calls.
    assert re.fullmatch(r"[0-9a-f]{64}", scripts[0]["sha256"])
    again = freeze.enumerate_scripts(IFF_ROOT)
    assert again == scripts


def test_counts_dynamic_against_live_iff() -> None:
    freeze = _load_freeze()
    required = freeze.parse_required_registry(IFF_ROOT / "scripts" / "verify_pipeline_scripts.py")
    scripts = freeze.enumerate_scripts(IFF_ROOT)
    counts = freeze.compute_counts(required, scripts)
    live_files = sorted(p.name for p in (IFF_ROOT / "scripts").glob("*.py"))
    required_names = {entry["name"] for entry in required}
    assert counts["scripts_total"] == len(live_files) == 165
    assert counts["required_registry_total"] == len(required) == 111
    assert counts["scripts_in_required"] == sum(1 for n in live_files if n in required_names)
    assert counts["scripts_not_in_required"] == counts["scripts_total"] - counts["scripts_in_required"]


def test_relationships_on_synthetic_iff() -> None:
    """AST import/caller/consume/produce proven on a tiny fixture."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        required = ["alpha.py", "beta.py", "gamma.py", "verify_pipeline_scripts.py",
                    "validate_skill_structure.py"]
        iff = _build_minimal_iff(root, required)
        scripts_dir = iff / "scripts"
        # Overwrite alpha/beta/gamma with content proving each relationship type.
        (scripts_dir / "alpha.py").write_text(
            "import json\n"
            "from beta import helper\n"
            "from pathlib import Path\n"
            "from common import load_json, dump_json\n"
            "def run(scene_path, out_path):\n"
            "    data = load_json('scene.json')\n"
            "    Path('canvas.dart').write_text('x', encoding='utf-8')\n"
            "    dump_json(data, 'render_plan.json')\n"
            "    helper()\n",
            encoding="utf-8",
        )
        (scripts_dir / "beta.py").write_text(
            "def helper():\n"
            "    return 0\n",
            encoding="utf-8",
        )
        (scripts_dir / "gamma.py").write_text(
            "# subprocess literal reference to alpha\n"
            "import subprocess, sys\n"
            "subprocess.run([sys.executable, 'alpha.py'])\n",
            encoding="utf-8",
        )
        freeze = _load_freeze()
        rels = freeze.compute_relationships(iff)
        alpha = next(r for r in rels if r["path"] == "iff/scripts/alpha.py")
        # importers of beta via `from beta import helper` (line 2)
        beta = next(r for r in rels if r["path"] == "iff/scripts/beta.py")
        assert "iff/scripts/alpha.py:2" in beta["direct_callers_or_importers"]
        # gamma references alpha.py via literal string (line 3)
        assert "iff/scripts/gamma.py:3" in alpha["direct_callers_or_importers"]
        # alpha consumes scene.json at line 6 (load_json literal)
        assert "iff/scripts/alpha.py:6:scene.json" in alpha["consumes"]
        # alpha produces canvas.dart at line 7 (Path().write_text literal)
        assert "iff/scripts/alpha.py:7:canvas.dart" in alpha["produces"]
        # alpha produces render_plan.json at line 8 (dump_json literal)
        assert "iff/scripts/alpha.py:8:render_plan.json" in alpha["produces"]
        # common is imported but is not present -> no entry; bare strings not
        # tied to a read/write call are NOT relationships.
        # The assertions above are the only relationships justified by the fixture.


def test_bare_strings_are_not_relationships() -> None:
    """Strings/comments alone must never become consumes/produces."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        required = ["alpha.py", "verify_pipeline_scripts.py", "validate_skill_structure.py"]
        iff = _build_minimal_iff(root, required)
        scripts_dir = iff / "scripts"
        (scripts_dir / "alpha.py").write_text(
            "# a comment mentions scene.json but no call\n"
            "NAME = 'render_plan.json'\n"
            "OTHER = \"a literal not tied to a recognized call\\n\"\n",
            encoding="utf-8",
        )
        freeze = _load_freeze()
        rels = freeze.compute_relationships(iff)
        alpha = next(r for r in rels if r["path"] == "iff/scripts/alpha.py")
        assert alpha["consumes"] == []
        assert alpha["produces"] == []


def test_gate_evidence_from_required_registry() -> None:
    """REQUIRED membership yields exactly one verifier-line gate evidence."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        required = ["alpha.py", "beta.py", "verify_pipeline_scripts.py", "validate_skill_structure.py"]
        iff = _build_minimal_iff(root, required)
        scripts_dir = iff / "scripts"
        (scripts_dir / "extra.py").write_text("# extra\n", encoding="utf-8")
        freeze = _load_freeze()
        verifier = scripts_dir / "verify_pipeline_scripts.py"
        # Locate the line number of each REQUIRED entry by parsing the file.
        vlines = verifier.read_text(encoding="utf-8").splitlines()
        alpha_line = next(i + 1 for i, ln in enumerate(vlines) if '"alpha.py"' in ln)
        required_entries = freeze.parse_required_registry(verifier)
        gates = freeze.gate_evidence(required_entries, iff)
        assert gates["alpha.py"] == [f"iff/scripts/verify_pipeline_scripts.py:{alpha_line}"]
        assert gates["beta.py"] != []
        # Non-REQUIRED scripts get no gate evidence (filename alone is never proof).
        assert gates["extra.py"] == []
        assert gates.get("validate_skill_structure.py", []) != []


def test_default_migration_metadata() -> None:
    """owner=unclassified, migration=hold, deletion evidence empty by default."""
    freeze = _load_freeze()
    assert freeze.default_owner() == "unclassified"
    assert freeze.default_migration() == "hold"
    assert freeze.default_deletion_evidence() == []


def test_run_verifier_records_command_exit_stdout() -> None:
    """The fixed verifier is run with sys.executable, shell=False, sanitized env."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        required = ["alpha.py", "verify_pipeline_scripts.py", "validate_skill_structure.py"]
        iff = _build_minimal_iff(root, required)
        freeze = _load_freeze()
        record = freeze.run_verifier(iff)
        assert record["exit_code"] == 0
        assert record["stdout"].startswith(f"ok {len(required)} scripts in ")
        assert record["command"][0] == "python3"
        assert record["command"][1] == "iff/scripts/verify_pipeline_scripts.py"
        assert record["command"][2] == "--skill-dir"
        assert record["command"][3] == "iff"
        # No machine-specific absolute path leaks into the recorded command.
        assert str(iff) not in record["command"]
        # Recorded stdout has the absolute path normalized to the iff/ relative root.
        assert str(iff.resolve()) not in record["stdout"]
        assert "iff/scripts" in record["stdout"]


def test_run_verifier_missing_required_exits_nonzero() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        required = ["alpha.py", "verify_pipeline_scripts.py", "validate_skill_structure.py"]
        iff = _build_minimal_iff(root, required)
        (iff / "scripts" / "alpha.py").unlink()
        freeze = _load_freeze()
        record = freeze.run_verifier(iff)
        assert record["exit_code"] != 0
        assert record["stdout"] == ""


def test_build_snapshot_covers_every_live_script_once() -> None:
    freeze = _load_freeze()
    snapshot, encoded = freeze.build_snapshot(IFF_ROOT)
    assert snapshot["kind"] == "iff-baseline-freeze"
    assert snapshot["schema_version"] == 1
    assert snapshot["counts"]["scripts_total"] == 165
    assert snapshot["counts"]["required_registry_total"] == 111
    scripts = snapshot["scripts"]
    paths = [entry["path"] for entry in scripts]
    assert paths == sorted(paths)
    assert len(paths) == len(set(paths)) == 165
    required_keys = {
        "path",
        "sha256",
        "in_required_registry",
        "direct_callers_or_importers",
        "consumes",
        "produces",
        "gates",
        "owner_candidate",
        "migration_action",
        "deletion_evidence",
    }
    assert all(set(entry) == required_keys for entry in scripts)
    assert snapshot["verifier"]["exit_code"] == 0
    assert encoded == freeze.canonical_json_bytes(snapshot)


def test_atomic_write_is_deterministic_and_refuses_symlink() -> None:
    freeze = _load_freeze()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        output = root / "baseline.json"
        payload = b'{"stable":true}\n'
        freeze.write_atomic(output, payload)
        assert output.read_bytes() == payload
        freeze.write_atomic(output, payload)
        assert output.read_bytes() == payload
        assert sorted(path.name for path in root.iterdir()) == ["baseline.json"]

        real_output = root / "real.json"
        real_output.write_bytes(b"sentinel\n")
        symlink_output = root / "linked.json"
        symlink_output.symlink_to(real_output)
        try:
            freeze.write_atomic(symlink_output, b"must-not-write\n")
        except (OSError, ValueError):
            pass
        else:
            raise AssertionError("write_atomic accepted a symlink output")
        assert real_output.read_bytes() == b"sentinel\n"


def test_cli_write_refuses_symlink_output() -> None:
    """The real CLI must not resolve away a symlink before write_atomic sees it."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        iff = _build_minimal_iff(root, ["alpha.py"])
        real_output = root / "real.json"
        real_output.write_bytes(b"sentinel\n")
        symlink_output = root / "linked.json"
        symlink_output.symlink_to(real_output)
        result = _run_cli(
            "--iff-root", str(iff), "--write", str(symlink_output)
        )
        assert result.returncode != 0, (
            f"CLI accepted symlink output: rc={result.returncode} "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert real_output.read_bytes() == b"sentinel\n"
        assert symlink_output.is_symlink()


def test_cli_check_refuses_symlink_baseline() -> None:
    """The real CLI --check must not resolve away a symlink baseline."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        iff = _build_minimal_iff(root, ["alpha.py"])
        real_baseline = root / "real.json"
        write_result = _run_cli(
            "--iff-root", str(iff), "--write", str(real_baseline)
        )
        assert write_result.returncode == 0
        real_bytes = real_baseline.read_bytes()
        symlink_baseline = root / "linked.json"
        symlink_baseline.symlink_to(real_baseline)
        result = _run_cli(
            "--iff-root", str(iff), "--check", str(symlink_baseline)
        )
        assert result.returncode != 0, (
            f"CLI accepted symlink baseline: rc={result.returncode} "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert real_baseline.read_bytes() == real_bytes
        assert symlink_baseline.is_symlink()


def test_write_mode_preserves_existing_output_when_required_script_is_missing() -> None:
    freeze = _load_freeze()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        iff = _build_minimal_iff(root, ["alpha.py"])
        (iff / "scripts" / "alpha.py").unlink()
        output = root / "baseline.json"
        output.write_bytes(b"sentinel\n")
        result = freeze.main(
            ["--iff-root", str(iff), "--write", str(output)]
        )
        assert result != 0
        assert output.read_bytes() == b"sentinel\n"


def test_check_mode_detects_drift_by_section_without_rewriting() -> None:
    freeze = _load_freeze()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        iff = _build_minimal_iff(root, ["alpha.py"])
        output = root / "baseline.json"
        assert freeze.main(
            ["--iff-root", str(iff), "--write", str(output)]
        ) == 0
        assert freeze.main(
            ["--iff-root", str(iff), "--check", str(output)]
        ) == 0

        drifted = json.loads(output.read_text(encoding="utf-8"))
        drifted["counts"]["scripts_total"] += 1
        output.write_text(
            json.dumps(drifted, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        drifted_bytes = output.read_bytes()
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            result = freeze.main(
                ["--iff-root", str(iff), "--check", str(output)]
            )
        assert result == 1
        assert "counts" in captured.getvalue()
        assert output.read_bytes() == drifted_bytes


def test_snapshot_evidence_has_relative_path_and_line() -> None:
    freeze = _load_freeze()
    snapshot, _ = freeze.build_snapshot(IFF_ROOT)
    evidence_fields = (
        "direct_callers_or_importers",
        "consumes",
        "produces",
        "gates",
        "deletion_evidence",
    )
    for script in snapshot["scripts"]:
        for field in evidence_fields:
            for evidence in script[field]:
                path, line, *_ = evidence.split(":", 2)
                assert path.startswith("iff/scripts/")
                assert line.isdigit() and int(line) > 0


def test_relationship_source_parse_failure_is_visible() -> None:
    freeze = _load_freeze()
    with tempfile.TemporaryDirectory() as tmp:
        iff = _build_minimal_iff(Path(tmp), ["alpha.py"], ["broken.py"])
        broken = iff / "scripts" / "broken.py"
        broken.write_text("def broken(:\n", encoding="utf-8")
        try:
            freeze.compute_relationships(iff)
        except SyntaxError as exc:
            assert "broken.py" in str(exc)
        else:
            raise AssertionError("invalid source was silently skipped")


def test_relationship_source_decode_failure_is_visible() -> None:
    """Undecodable bytes are a read failure: visible, naming the relative path."""
    freeze = _load_freeze()
    with tempfile.TemporaryDirectory() as tmp:
        iff = _build_minimal_iff(Path(tmp), ["alpha.py"], ["broken.py"])
        broken = iff / "scripts" / "broken.py"
        broken.write_bytes(b"\xff\xfe invalid utf-8 \x00\x01\n")
        try:
            freeze.compute_relationships(iff)
        except ValueError as exc:
            assert "broken.py" in str(exc)
        else:
            raise AssertionError("undecodable source was silently skipped")


def test_relationship_source_read_failure_is_visible() -> None:
    """Unreadable source is visible and names the relative path (never skipped)."""
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return  # root can read anything; permission failure is not simulatable.
    freeze = _load_freeze()
    with tempfile.TemporaryDirectory() as tmp:
        iff = _build_minimal_iff(Path(tmp), ["alpha.py"], ["broken.py"])
        broken = iff / "scripts" / "broken.py"
        broken.chmod(0o000)
        try:
            freeze.compute_relationships(iff)
        except OSError as exc:
            assert "broken.py" in str(exc)
        else:
            raise AssertionError("unreadable source was silently skipped")
        finally:
            broken.chmod(0o644)


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
