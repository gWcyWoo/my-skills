from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("icp_page_job_v1.py")


def _make_project(root: Path) -> tuple[Path, str]:
    project_root = root / "project"
    project_root.mkdir()
    (project_root / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=project_root, check=True)
    subprocess.run(["git", "add", "README.md"], cwd=project_root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=ICP Selftest",
            "-c",
            "user.email=icp-selftest@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=project_root,
        check=True,
    )
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return project_root, revision


def _job(project_root: Path, base_revision: str) -> dict:
    return {
        "kind": "icp.external-page-job.v1",
        "schema_version": 1,
        "job_id": "excel:book-a:sheet-1:row-42",
        "row_digest": "a" * 64,
        "project_root": str(project_root),
        "base_revision": base_revision,
        "platform": "nextjs",
        "profile": "nextjs-standard",
        "design_source": "lanhu-figma",
        "design_ref": "https://lanhuapp.com/web/#/item/project/detailDetach?image_id=42",
        "page": {
            "title": "Loan home",
            "route": "/",
            "requirement": "Implement the supplied page design.",
            "acceptance_criteria": ["Matches the supplied design."],
        },
    }


def _job_v2(project_root: Path, base_revision: str) -> dict:
    document = _job(project_root, base_revision)
    document.update(
        {
            "kind": "icp.external-page-job.v2",
            "schema_version": 2,
            "job_id": "iole:client:row-42:review-2:aaaaaaaaaaaa",
            "role": "client",
            "mode": "revise",
            "review": {"number": 2, "text": "点击按钮没有跳转"},
        }
    )
    return document


def test_prepare_accepts_an_iole_client_revision_job() -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        project_root, base_revision = _make_project(Path(temporary_directory))
        job_path = Path(temporary_directory) / "job-v2.json"
        job_path.write_text(
            json.dumps(_job_v2(project_root, base_revision)),
            encoding="utf-8",
        )
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "prepare", "--job", str(job_path)],
            check=False,
            capture_output=True,
            text=True,
        )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["status"] == "ready"


def test_prepare_accepts_empty_external_acceptance_criteria() -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        project_root, base_revision = _make_project(Path(temporary_directory))
        job = _job_v2(project_root, base_revision)
        job["page"]["acceptance_criteria"] = []
        job_path = Path(temporary_directory) / "job-v2.json"
        job_path.write_text(json.dumps(job), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "prepare", "--job", str(job_path)],
            check=False,
            capture_output=True,
            text=True,
        )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["status"] == "ready"


def test_prepare_rejects_a_non_client_iole_job() -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        project_root, base_revision = _make_project(Path(temporary_directory))
        document = _job_v2(project_root, base_revision)
        document["role"] = "backend"
        job_path = Path(temporary_directory) / "backend-job.json"
        job_path.write_text(json.dumps(document), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "prepare", "--job", str(job_path)],
            check=False,
            capture_output=True,
            text=True,
        )

    assert completed.returncode == 2
    decision = json.loads(completed.stdout)
    assert decision["status"] == "invalid-input"
    assert decision["reason"] == "job_schema_invalid"


def test_prepare_rejects_review_data_in_implement_mode() -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        project_root, base_revision = _make_project(Path(temporary_directory))
        document = _job_v2(project_root, base_revision)
        document["mode"] = "implement"
        job_path = Path(temporary_directory) / "invalid-mode-job.json"
        job_path.write_text(json.dumps(document), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "prepare", "--job", str(job_path)],
            check=False,
            capture_output=True,
            text=True,
        )

    assert completed.returncode == 2
    decision = json.loads(completed.stdout)
    assert decision["status"] == "invalid-input"
    assert decision["reason"] == "job_schema_invalid"


def test_prepare_rejects_malformed_v2_field_types_without_a_traceback() -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        project_root, base_revision = _make_project(Path(temporary_directory))
        cases = []

        bad_job_id = _job_v2(project_root, base_revision)
        bad_job_id["job_id"] = 42
        cases.append(bad_job_id)

        bad_platform = _job_v2(project_root, base_revision)
        bad_platform["platform"] = ["nextjs"]
        cases.append(bad_platform)

        bad_acceptance = _job_v2(project_root, base_revision)
        bad_acceptance["page"]["acceptance_criteria"] = "not-a-list"
        cases.append(bad_acceptance)

        for index, document in enumerate(cases):
            job_path = Path(temporary_directory) / f"malformed-{index}.json"
            job_path.write_text(json.dumps(document), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "prepare", "--job", str(job_path)],
                check=False,
                capture_output=True,
                text=True,
            )

            assert completed.returncode == 2, completed.stderr
            decision = json.loads(completed.stdout)
            assert decision["status"] == "invalid-input"
            assert decision["reason"] == "job_schema_invalid"
            assert "Traceback" not in completed.stderr


def test_prepare_rejects_a_symlinked_page_job_state_root() -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        project_root, base_revision = _make_project(root)
        external_state = root / "external-state"
        external_state.mkdir()
        (project_root / ".icp").symlink_to(external_state, target_is_directory=True)
        job_path = root / "job.json"
        job_path.write_text(
            json.dumps(_job_v2(project_root, base_revision)),
            encoding="utf-8",
        )
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "prepare", "--job", str(job_path)],
            check=False,
            capture_output=True,
            text=True,
        )

    assert completed.returncode == 2, completed.stderr
    decision = json.loads(completed.stdout)
    assert decision["status"] == "invalid-input"
    assert decision["reason"] == "job_schema_invalid"


def _write_valid_evidence(
    state_root: Path,
    decision: dict,
    platform: str = "nextjs",
) -> Path:
    actual_source = {
        "android-java": "emulator_screenshot",
        "android-kotlin": "emulator_screenshot",
        "flutter": "simulator_screenshot",
        "ios-objc": "simulator_screenshot",
        "ios-swift": "simulator_screenshot",
        "nextjs": "browser_screenshot",
        "vue": "browser_screenshot",
    }[platform]
    (state_root / "page-tests.txt").write_text("passed\n", encoding="utf-8")
    (state_root / "actual.png").write_bytes(b"runtime-capture")
    (state_root / "visual-comparison.json").write_text("{}\n", encoding="utf-8")
    page_tests_digest = hashlib.sha256(
        (state_root / "page-tests.txt").read_bytes()
    ).hexdigest()
    runtime_digest = hashlib.sha256((state_root / "actual.png").read_bytes()).hexdigest()
    visual_digest = hashlib.sha256(
        (state_root / "visual-comparison.json").read_bytes()
    ).hexdigest()
    evidence_path = state_root / "evidence-manifest.json"
    evidence_path.write_text(
        json.dumps(
            {
                "kind": "icp.page-evidence-manifest.v1",
                "schema_version": 1,
                "job_id": decision["job_id"],
                "job_digest": decision["job_digest"],
                "artifacts": {
                    "page_tests": {
                        "status": "passed",
                        "path": "page-tests.txt",
                        "sha256": page_tests_digest,
                    },
                    "runtime_capture": {
                        "status": "passed",
                        "path": "actual.png",
                        "actual_source": actual_source,
                        "sha256": runtime_digest,
                    },
                    "visual": {
                        "status": "passed",
                        "path": "visual-comparison.json",
                        "sha256": visual_digest,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return evidence_path


def test_prepare_accepts_one_external_page_job_without_csv() -> None:
    with tempfile.TemporaryDirectory(prefix="icp_page_job_") as tmp:
        root = Path(tmp)
        project_root, base_revision = _make_project(root)
        job_path = root / "job.json"
        job_path.write_text(
            json.dumps(_job(project_root, base_revision)), encoding="utf-8"
        )
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "prepare", "--job", str(job_path)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert completed.returncode == 0, completed.stderr
        decision = json.loads(completed.stdout)
        assert decision["kind"] == "icp.page-job-decision.v1"
        assert decision["status"] == "ready"
        assert decision["job_id"] == "excel:book-a:sheet-1:row-42"
        assert "task_ref" not in decision


def test_prepare_rejects_invalid_job_before_project_changes() -> None:
    with tempfile.TemporaryDirectory(prefix="icp_page_job_") as tmp:
        root = Path(tmp)
        project_root, base_revision = _make_project(root)
        job = _job(project_root, base_revision)
        del job["design_ref"]
        job_path = root / "job.json"
        job_path.write_text(json.dumps(job), encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "prepare", "--job", str(job_path)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert completed.returncode == 2
        decision = json.loads(completed.stdout)
        assert decision["status"] == "invalid-input"
        assert decision["reason"] == "job_schema_invalid"
        assert not (project_root / ".icp").exists()


def test_prepare_reports_an_unreadable_job_without_leaking_its_path() -> None:
    with tempfile.TemporaryDirectory(prefix="icp_page_job_") as tmp:
        missing_path = Path(tmp) / "private-job.json"
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "prepare", "--job", str(missing_path)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert completed.returncode == 2
        decision = json.loads(completed.stdout)
        assert decision["status"] == "invalid-input"
        assert decision["reason"] == "job-unreadable"
        assert str(missing_path) not in completed.stdout
        assert str(missing_path) not in completed.stderr


def test_prepare_rejects_a_worktree_at_the_wrong_base_revision() -> None:
    with tempfile.TemporaryDirectory(prefix="icp_page_job_") as tmp:
        root = Path(tmp)
        project_root, base_revision = _make_project(root)
        job = _job(project_root, "f" * len(base_revision))
        job_path = root / "job.json"
        job_path.write_text(json.dumps(job), encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "prepare", "--job", str(job_path)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert completed.returncode == 2
        decision = json.loads(completed.stdout)
        assert decision["status"] == "invalid-input"
        assert decision["reason"] == "base-revision-mismatch"
        assert not (project_root / ".icp").exists()


def test_prepare_rejects_an_unregistered_platform_profile_pair() -> None:
    with tempfile.TemporaryDirectory(prefix="icp_page_job_") as tmp:
        root = Path(tmp)
        project_root, base_revision = _make_project(root)
        job = _job(project_root, base_revision)
        job["profile"] = "vue-vite"
        job_path = root / "job.json"
        job_path.write_text(json.dumps(job), encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "prepare", "--job", str(job_path)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert completed.returncode == 2
        decision = json.loads(completed.stdout)
        assert decision["status"] == "invalid-input"
        assert decision["reason"] == "unsupported-platform-profile"
        assert not (project_root / ".icp").exists()


def test_prepare_rejects_a_malformed_row_digest() -> None:
    with tempfile.TemporaryDirectory(prefix="icp_page_job_") as tmp:
        root = Path(tmp)
        project_root, base_revision = _make_project(root)
        job = _job(project_root, base_revision)
        job["row_digest"] = "not-a-sha256"
        job_path = root / "job.json"
        job_path.write_text(json.dumps(job), encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "prepare", "--job", str(job_path)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert completed.returncode == 2
        decision = json.loads(completed.stdout)
        assert decision["status"] == "invalid-input"
        assert decision["reason"] == "job_schema_invalid"
        assert not (project_root / ".icp").exists()


def test_prepare_rejects_a_relative_job_path() -> None:
    with tempfile.TemporaryDirectory(prefix="icp_page_job_") as tmp:
        root = Path(tmp)
        project_root, base_revision = _make_project(root)
        job_path = root / "job.json"
        job_path.write_text(
            json.dumps(_job(project_root, base_revision)), encoding="utf-8"
        )
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "prepare", "--job", "job.json"],
            check=False,
            capture_output=True,
            text=True,
            cwd=root,
            env=env,
        )
        assert completed.returncode == 2
        assert json.loads(completed.stdout)["reason"] == "job_schema_invalid"
        assert not (project_root / ".icp").exists()


def test_prepare_rejects_the_wrong_job_contract_version() -> None:
    with tempfile.TemporaryDirectory(prefix="icp_page_job_") as tmp:
        root = Path(tmp)
        project_root, base_revision = _make_project(root)
        job = _job(project_root, base_revision)
        job["kind"] = "icp.external-page-job.v2"
        job["schema_version"] = 2
        job_path = root / "job.json"
        job_path.write_text(json.dumps(job), encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "prepare", "--job", str(job_path)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert completed.returncode == 2
        decision = json.loads(completed.stdout)
        assert decision["status"] == "invalid-input"
        assert decision["reason"] == "job_schema_invalid"
        assert not (project_root / ".icp").exists()


def test_prepare_rejects_a_non_absolute_web_page_route() -> None:
    with tempfile.TemporaryDirectory(prefix="icp_page_job_") as tmp:
        root = Path(tmp)
        project_root, base_revision = _make_project(root)
        job = _job(project_root, base_revision)
        job["page"]["route"] = "loan/home"
        job_path = root / "job.json"
        job_path.write_text(json.dumps(job), encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "prepare", "--job", str(job_path)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert completed.returncode == 2
        decision = json.loads(completed.stdout)
        assert decision["status"] == "invalid-input"
        assert decision["reason"] == "job_schema_invalid"
        assert not (project_root / ".icp").exists()


def test_prepare_rejects_control_characters_in_page_route() -> None:
    with tempfile.TemporaryDirectory(prefix="icp_page_job_") as tmp:
        root = Path(tmp)
        project_root, base_revision = _make_project(root)
        job = _job(project_root, base_revision)
        job["page"]["route"] = "/loan/home\ninjected"
        job_path = root / "job.json"
        job_path.write_text(json.dumps(job), encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "prepare", "--job", str(job_path)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert completed.returncode == 2
        decision = json.loads(completed.stdout)
        assert decision["status"] == "invalid-input"
        assert decision["reason"] == "job_schema_invalid"
        assert not (project_root / ".icp").exists()


def test_prepare_accepts_a_native_page_target_without_a_leading_slash() -> None:
    platform_profiles = (
        ("flutter", "flutter-standard"),
        ("ios-swift", "ios-swift-standard"),
        ("ios-objc", "ios-objc-standard"),
        ("android-java", "android-java-standard"),
        ("android-kotlin", "android-kotlin-standard"),
    )
    for platform, profile in platform_profiles:
        with tempfile.TemporaryDirectory(prefix="icp_page_job_") as tmp:
            root = Path(tmp)
            project_root, base_revision = _make_project(root)
            job = _job(project_root, base_revision)
            job["platform"] = platform
            job["profile"] = profile
            job["page"]["route"] = "common-card"
            job_path = root / "job.json"
            job_path.write_text(json.dumps(job), encoding="utf-8")
            env = dict(os.environ)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "prepare", "--job", str(job_path)],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )

            assert completed.returncode == 0, (platform, completed.stderr)
            decision = json.loads(completed.stdout)
            assert decision["status"] == "ready", platform


def test_prepare_resumes_the_same_page_job_without_duplicate_work() -> None:
    with tempfile.TemporaryDirectory(prefix="icp_page_job_") as tmp:
        root = Path(tmp)
        project_root, base_revision = _make_project(root)
        job_path = root / "job.json"
        job_path.write_text(
            json.dumps(_job(project_root, base_revision)), encoding="utf-8"
        )
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        command = [sys.executable, str(SCRIPT), "prepare", "--job", str(job_path)]
        first = subprocess.run(
            command, check=False, capture_output=True, text=True, env=env
        )
        second = subprocess.run(
            command, check=False, capture_output=True, text=True, env=env
        )
        assert first.returncode == 0, first.stderr
        assert second.returncode == 0, second.stderr
        first_decision = json.loads(first.stdout)
        second_decision = json.loads(second.stdout)
        assert first_decision["status"] == "ready"
        assert second_decision["status"] == "resume-required"
        assert second_decision["job_digest"] == first_decision["job_digest"]
        assert second_decision["state_root"] == first_decision["state_root"]


def test_prepare_blocks_when_the_same_job_id_has_input_drift() -> None:
    with tempfile.TemporaryDirectory(prefix="icp_page_job_") as tmp:
        root = Path(tmp)
        project_root, base_revision = _make_project(root)
        job_path = root / "job.json"
        job = _job(project_root, base_revision)
        job_path.write_text(json.dumps(job), encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        command = [sys.executable, str(SCRIPT), "prepare", "--job", str(job_path)]
        first = subprocess.run(
            command, check=False, capture_output=True, text=True, env=env
        )
        assert first.returncode == 0, first.stderr
        job["row_digest"] = "c" * 64
        job_path.write_text(json.dumps(job), encoding="utf-8")
        second = subprocess.run(
            command, check=False, capture_output=True, text=True, env=env
        )
        assert second.returncode == 3
        decision = json.loads(second.stdout)
        assert decision["status"] == "blocked"
        assert decision["reason"] == "input-drift"


def test_finalize_publishes_ready_for_pr_without_pr_or_excel_fields() -> None:
    with tempfile.TemporaryDirectory(prefix="icp_page_job_") as tmp:
        root = Path(tmp)
        project_root, base_revision = _make_project(root)
        job_path = root / "job.json"
        job_path.write_text(
            json.dumps(_job(project_root, base_revision)), encoding="utf-8"
        )
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        prepared = subprocess.run(
            [sys.executable, str(SCRIPT), "prepare", "--job", str(job_path)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert prepared.returncode == 0, prepared.stderr
        decision = json.loads(prepared.stdout)
        page_path = project_root / "app" / "page.tsx"
        page_path.parent.mkdir()
        page_path.write_text("export default function Page() { return null }\n")
        evidence_path = Path(decision["state_root"]) / "evidence-manifest.json"
        evidence_path.write_text("{}\n", encoding="utf-8")
        outside_evidence = evidence_path.parent.parent / "outside-evidence.json"
        outside_evidence.write_text("{}\n", encoding="utf-8")
        traversal_handoff = root / "traversal-handoff.json"
        traversal_handoff.write_text(
            json.dumps(
                {
                    "kind": "icp.page-handoff-input.v1",
                    "schema_version": 1,
                    "status": "ready-for-pr",
                    "changed_files": ["app/page.tsx"],
                    "verification": {
                        "page_tests": "passed",
                        "runtime_capture": "passed",
                        "visual": "passed",
                    },
                    "evidence_manifest": str(
                        evidence_path.parent / ".." / "outside-evidence.json"
                    ),
                }
            ),
            encoding="utf-8",
        )
        traversal_result = root / "traversal-result.json"
        traversal = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "finalize",
                "--job",
                str(job_path),
                "--handoff",
                str(traversal_handoff),
                "--result",
                str(traversal_result),
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert traversal.returncode == 4, (traversal.stdout, traversal.stderr)
        assert json.loads(traversal.stdout)["reason"] == "page-evidence-missing"
        assert not traversal_result.exists()
        handoff_path = root / "handoff.json"
        handoff_path.write_text(
            json.dumps(
                {
                    "kind": "icp.page-handoff-input.v1",
                    "schema_version": 1,
                    "status": "ready-for-pr",
                    "changed_files": ["app/page.tsx"],
                    "verification": {
                        "page_tests": "passed",
                        "runtime_capture": "passed",
                        "visual": "passed",
                    },
                    "evidence_manifest": str(evidence_path),
                }
            ),
            encoding="utf-8",
        )
        forbidden_handoff_path = root / "forbidden-handoff.json"
        forbidden_handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
        forbidden_handoff["pr_url"] = "https://git.example/pr/1"
        forbidden_handoff_path.write_text(
            json.dumps(forbidden_handoff),
            encoding="utf-8",
        )
        forbidden_result = root / "forbidden-result.json"
        forbidden = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "finalize",
                "--job",
                str(job_path),
                "--handoff",
                str(forbidden_handoff_path),
                "--result",
                str(forbidden_result),
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert forbidden.returncode == 2, (forbidden.stdout, forbidden.stderr)
        assert json.loads(forbidden.stdout)["reason"] == "job_schema_invalid"
        assert not forbidden_result.exists()
        empty_manifest_result = root / "empty-manifest-result.json"
        empty_manifest = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "finalize",
                "--job",
                str(job_path),
                "--handoff",
                str(handoff_path),
                "--result",
                str(empty_manifest_result),
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert empty_manifest.returncode == 4, (
            empty_manifest.stdout,
            empty_manifest.stderr,
        )
        assert json.loads(empty_manifest.stdout)["reason"] == "page-evidence-missing"
        assert not empty_manifest_result.exists()
        _write_valid_evidence(evidence_path.parent, decision)
        (evidence_path.parent / "page-tests.txt").write_text(
            "tampered\n", encoding="utf-8"
        )
        tampered_result = root / "tampered-result.json"
        tampered = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "finalize",
                "--job",
                str(job_path),
                "--handoff",
                str(handoff_path),
                "--result",
                str(tampered_result),
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert tampered.returncode == 4, (tampered.stdout, tampered.stderr)
        assert json.loads(tampered.stdout)["reason"] == "page-evidence-missing"
        assert not tampered_result.exists()
        _write_valid_evidence(evidence_path.parent, decision)
        result_path = root / "result.json"
        finalized = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "finalize",
                "--job",
                str(job_path),
                "--handoff",
                str(handoff_path),
                "--result",
                str(result_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert finalized.returncode == 0, finalized.stderr
        result = json.loads(result_path.read_text(encoding="utf-8"))
        assert result["kind"] == "icp.page-handoff-result.v1"
        assert result["status"] == "ready-for-pr"
        assert result["job_id"] == "excel:book-a:sheet-1:row-42"
        assert result["changed_files"] == ["app/page.tsx"]
        assert result["evidence_manifest_digest"] == hashlib.sha256(
            evidence_path.read_bytes()
        ).hexdigest()
        assert "pr_url" not in result
        assert "status_url" not in result


def test_finalize_rejects_ready_for_pr_when_page_verification_failed() -> None:
    with tempfile.TemporaryDirectory(prefix="icp_page_job_") as tmp:
        root = Path(tmp)
        project_root, base_revision = _make_project(root)
        job_path = root / "job.json"
        job_path.write_text(
            json.dumps(_job(project_root, base_revision)), encoding="utf-8"
        )
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        prepared = subprocess.run(
            [sys.executable, str(SCRIPT), "prepare", "--job", str(job_path)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert prepared.returncode == 0, prepared.stderr
        decision = json.loads(prepared.stdout)
        evidence_path = Path(decision["state_root"]) / "evidence-manifest.json"
        evidence_path.write_text("{}\n", encoding="utf-8")
        handoff_path = root / "handoff.json"
        handoff_path.write_text(
            json.dumps(
                {
                    "kind": "icp.page-handoff-input.v1",
                    "schema_version": 1,
                    "status": "ready-for-pr",
                    "changed_files": ["app/page.tsx"],
                    "verification": {
                        "page_tests": "passed",
                        "runtime_capture": "passed",
                        "visual": "failed",
                    },
                    "evidence_manifest": str(evidence_path),
                }
            ),
            encoding="utf-8",
        )
        result_path = root / "result.json"
        finalized = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "finalize",
                "--job",
                str(job_path),
                "--handoff",
                str(handoff_path),
                "--result",
                str(result_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert finalized.returncode == 4
        decision = json.loads(finalized.stdout)
        assert decision["status"] == "verification-failed"
        assert decision["reason"] == "page-verification-not-passed"
        assert not result_path.exists()


def test_finalize_rejects_ready_for_pr_without_evidence_manifest() -> None:
    with tempfile.TemporaryDirectory(prefix="icp_page_job_") as tmp:
        root = Path(tmp)
        project_root, base_revision = _make_project(root)
        job_path = root / "job.json"
        job_path.write_text(
            json.dumps(_job(project_root, base_revision)), encoding="utf-8"
        )
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        prepared = subprocess.run(
            [sys.executable, str(SCRIPT), "prepare", "--job", str(job_path)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert prepared.returncode == 0, prepared.stderr
        state_root = Path(json.loads(prepared.stdout)["state_root"])
        handoff_path = root / "handoff.json"
        handoff_path.write_text(
            json.dumps(
                {
                    "kind": "icp.page-handoff-input.v1",
                    "schema_version": 1,
                    "status": "ready-for-pr",
                    "changed_files": ["app/page.tsx"],
                    "verification": {
                        "page_tests": "passed",
                        "runtime_capture": "passed",
                        "visual": "passed",
                    },
                    "evidence_manifest": str(state_root / "missing-evidence.json"),
                }
            ),
            encoding="utf-8",
        )
        result_path = root / "result.json"
        finalized = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "finalize",
                "--job",
                str(job_path),
                "--handoff",
                str(handoff_path),
                "--result",
                str(result_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert finalized.returncode == 4
        decision = json.loads(finalized.stdout)
        assert decision["status"] == "verification-failed"
        assert decision["reason"] == "page-evidence-missing"
        assert not result_path.exists()


def test_finalize_rejects_changed_files_outside_the_worktree() -> None:
    with tempfile.TemporaryDirectory(prefix="icp_page_job_") as tmp:
        root = Path(tmp)
        project_root, base_revision = _make_project(root)
        job_path = root / "job.json"
        job_path.write_text(
            json.dumps(_job(project_root, base_revision)), encoding="utf-8"
        )
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        prepared = subprocess.run(
            [sys.executable, str(SCRIPT), "prepare", "--job", str(job_path)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert prepared.returncode == 0, prepared.stderr
        decision = json.loads(prepared.stdout)
        state_root = Path(decision["state_root"])
        evidence_path = _write_valid_evidence(state_root, decision)
        handoff_path = root / "handoff.json"
        handoff_path.write_text(
            json.dumps(
                {
                    "kind": "icp.page-handoff-input.v1",
                    "schema_version": 1,
                    "status": "ready-for-pr",
                    "changed_files": ["../outside.tsx"],
                    "verification": {
                        "page_tests": "passed",
                        "runtime_capture": "passed",
                        "visual": "passed",
                    },
                    "evidence_manifest": str(evidence_path),
                }
            ),
            encoding="utf-8",
        )
        result_path = root / "result.json"
        finalized = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "finalize",
                "--job",
                str(job_path),
                "--handoff",
                str(handoff_path),
                "--result",
                str(result_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert finalized.returncode == 4
        decision = json.loads(finalized.stdout)
        assert decision["status"] == "verification-failed"
        assert decision["reason"] == "page-changes-invalid"
        assert not result_path.exists()
        real_directory = project_root / "real"
        real_directory.mkdir()
        (real_directory / "page.tsx").write_text("export default 1\n", encoding="utf-8")
        (project_root / "linked").symlink_to(real_directory, target_is_directory=True)
        symlink_handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
        symlink_handoff["changed_files"] = ["linked/page.tsx"]
        symlink_handoff_path = root / "symlink-handoff.json"
        symlink_handoff_path.write_text(
            json.dumps(symlink_handoff),
            encoding="utf-8",
        )
        symlink_result = root / "symlink-result.json"
        symlinked = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "finalize",
                "--job",
                str(job_path),
                "--handoff",
                str(symlink_handoff_path),
                "--result",
                str(symlink_result),
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert symlinked.returncode == 4
        assert json.loads(symlinked.stdout)["reason"] == "page-changes-invalid"
        assert not symlink_result.exists()


def test_finalize_is_idempotent_for_the_same_page_handoff() -> None:
    with tempfile.TemporaryDirectory(prefix="icp_page_job_") as tmp:
        root = Path(tmp)
        project_root, base_revision = _make_project(root)
        job_path = root / "job.json"
        job_path.write_text(
            json.dumps(_job(project_root, base_revision)), encoding="utf-8"
        )
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        prepared = subprocess.run(
            [sys.executable, str(SCRIPT), "prepare", "--job", str(job_path)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert prepared.returncode == 0, prepared.stderr
        decision = json.loads(prepared.stdout)
        state_root = Path(decision["state_root"])
        page_path = project_root / "app" / "page.tsx"
        page_path.parent.mkdir()
        page_path.write_text("export default function Page() { return null }\n")
        evidence_path = _write_valid_evidence(state_root, decision)
        handoff_path = root / "handoff.json"
        handoff_path.write_text(
            json.dumps(
                {
                    "kind": "icp.page-handoff-input.v1",
                    "schema_version": 1,
                    "status": "ready-for-pr",
                    "changed_files": ["app/page.tsx"],
                    "verification": {
                        "page_tests": "passed",
                        "runtime_capture": "passed",
                        "visual": "passed",
                    },
                    "evidence_manifest": str(evidence_path),
                }
            ),
            encoding="utf-8",
        )
        result_path = root / "result.json"
        command = [
            sys.executable,
            str(SCRIPT),
            "finalize",
            "--job",
            str(job_path),
            "--handoff",
            str(handoff_path),
            "--result",
            str(result_path),
        ]
        first = subprocess.run(
            command, check=False, capture_output=True, text=True, env=env
        )
        first_bytes = result_path.read_bytes()
        second = subprocess.run(
            command, check=False, capture_output=True, text=True, env=env
        )
        assert first.returncode == 0, first.stderr
        assert second.returncode == 0, second.stderr
        assert json.loads(second.stdout) == json.loads(first.stdout)
        assert result_path.read_bytes() == first_bytes
        moved_state_root = state_root.with_name(f"{state_root.name}-real")
        state_root.rename(moved_state_root)
        state_root.symlink_to(moved_state_root, target_is_directory=True)
        symlinked_state = subprocess.run(
            command, check=False, capture_output=True, text=True, env=env
        )
        assert symlinked_state.returncode == 2, (
            symlinked_state.stdout,
            symlinked_state.stderr,
        )
        assert json.loads(symlinked_state.stdout)["reason"] == "job_schema_invalid"


def main() -> int:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"ok {test.__name__}")
        except Exception as exc:
            failures += 1
            print(f"not ok {test.__name__}: {type(exc).__name__}: {exc}")
    if failures:
        print(f"failed {failures}/{len(tests)} selftest cases")
        return 1
    print(f"ok {len(tests)} selftest cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
