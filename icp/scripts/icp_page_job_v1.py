from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


REQUIRED_JOB_KEYS_V1 = {
    "base_revision",
    "design_ref",
    "design_source",
    "job_id",
    "kind",
    "page",
    "platform",
    "profile",
    "project_root",
    "row_digest",
    "schema_version",
}
REQUIRED_JOB_KEYS_V2 = REQUIRED_JOB_KEYS_V1 | {"mode", "review", "role"}
SHA256_HEX = re.compile(r"[0-9a-f]{64}")
GIT_REVISION = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
REQUIRED_PAGE_KEYS = {"acceptance_criteria", "requirement", "route", "title"}
REQUIRED_REVIEW_KEYS = {"number", "text"}
ABSOLUTE_ROUTE_PLATFORMS = {"nextjs", "vue"}
RUNTIME_CAPTURE_SOURCES = {
    "android-java": "emulator_screenshot",
    "android-kotlin": "emulator_screenshot",
    "flutter": "simulator_screenshot",
    "ios-objc": "simulator_screenshot",
    "ios-swift": "simulator_screenshot",
    "nextjs": "browser_screenshot",
    "vue": "browser_screenshot",
}


class JobValidationError(ValueError):
    pass


class JobUnreadableError(JobValidationError):
    pass


class PageVerificationError(ValueError):
    pass


class PageEvidenceError(PageVerificationError):
    pass


class PageChangesError(PageVerificationError):
    pass


class BaseRevisionError(JobValidationError):
    pass


class PlatformProfileError(JobValidationError):
    pass


def _load_job(path: Path) -> dict:
    if not path.is_absolute():
        raise JobValidationError("job path must be absolute")
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise JobUnreadableError("job cannot be read") from exc
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise JobValidationError("job is not valid JSON") from exc
    if not isinstance(document, dict):
        raise JobValidationError("job must be a JSON object")
    if not isinstance(document.get("kind"), str) or type(
        document.get("schema_version")
    ) is not int:
        raise JobValidationError("job contract version is invalid")
    contract = (document["kind"], document["schema_version"])
    if contract == ("icp.external-page-job.v1", 1):
        required_keys = REQUIRED_JOB_KEYS_V1
    elif contract == ("icp.external-page-job.v2", 2):
        required_keys = REQUIRED_JOB_KEYS_V2
    else:
        raise JobValidationError("job contract version is invalid")
    if set(document) != required_keys:
        raise JobValidationError("job keys do not match the contract")
    if contract == ("icp.external-page-job.v2", 2):
        if document["role"] != "client":
            raise JobValidationError("v2 role must be client")
        review = document["review"]
        if document["mode"] == "implement":
            if review is not None:
                raise JobValidationError("implement mode cannot contain review data")
        elif document["mode"] == "revise":
            if (
                not isinstance(review, dict)
                or set(review) != REQUIRED_REVIEW_KEYS
                or type(review["number"]) is not int
                or review["number"] <= 0
                or not isinstance(review["text"], str)
                or not review["text"].strip()
            ):
                raise JobValidationError("revise mode requires one numbered review")
        else:
            raise JobValidationError("v2 mode is invalid")
    if not isinstance(document["row_digest"], str) or not SHA256_HEX.fullmatch(
        document["row_digest"]
    ):
        raise JobValidationError("row_digest must be lowercase SHA-256")
    for key in ("design_ref", "design_source", "job_id", "platform", "profile"):
        if not isinstance(document[key], str) or not document[key].strip():
            raise JobValidationError(f"{key} must be a non-empty string")
    if (
        not isinstance(document["base_revision"], str)
        or not GIT_REVISION.fullmatch(document["base_revision"])
    ):
        raise JobValidationError("base_revision must be a lowercase Git revision")
    if (
        not isinstance(document["project_root"], str)
        or not document["project_root"]
        or not Path(document["project_root"]).is_absolute()
    ):
        raise JobValidationError("project_root must be an absolute path")
    page = document["page"]
    if not isinstance(page, dict) or set(page) != REQUIRED_PAGE_KEYS:
        raise JobValidationError("page keys do not match the contract")
    for key in ("requirement", "title"):
        if not isinstance(page[key], str) or not page[key].strip():
            raise JobValidationError(f"page {key} must be a non-empty string")
    acceptance = page["acceptance_criteria"]
    if (
        not isinstance(acceptance, list)
        or any(not isinstance(item, str) or not item.strip() for item in acceptance)
    ):
        raise JobValidationError("page acceptance_criteria must be a list of non-empty strings")
    route = page["route"]
    if (
        not isinstance(route, str)
        or not route.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in route)
    ):
        raise JobValidationError("page target is required")
    if document["platform"] in ABSOLUTE_ROUTE_PLATFORMS and not route.startswith("/"):
        raise JobValidationError("web page route must be absolute")
    return document


def _canonical_bytes(value: dict) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _require_state_artifact(state_root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative:
        raise PageEvidenceError("page evidence artifact path is invalid")
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise PageEvidenceError("page evidence artifact path is invalid")
    target = state_root / relative_path
    try:
        target.resolve(strict=True).relative_to(state_root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise PageEvidenceError("page evidence artifact is outside the job state") from exc
    if (
        target.is_symlink()
        or any(
            (state_root.joinpath(*relative_path.parts[:index])).is_symlink()
            for index in range(1, len(relative_path.parts))
        )
        or not target.is_file()
        or target.stat().st_size == 0
    ):
        raise PageEvidenceError("page evidence artifact is missing")
    return target.resolve(strict=True)


def _validate_evidence_manifest(
    evidence_path: Path,
    state_root: Path,
    job: dict,
    job_digest: str,
) -> None:
    try:
        manifest = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PageEvidenceError("page evidence manifest is unreadable") from exc
    if not isinstance(manifest, dict) or set(manifest) != {
        "artifacts",
        "job_digest",
        "job_id",
        "kind",
        "schema_version",
    }:
        raise PageEvidenceError("page evidence manifest contract is invalid")
    if (
        manifest["kind"] != "icp.page-evidence-manifest.v1"
        or manifest["schema_version"] != 1
        or manifest["job_id"] != job["job_id"]
        or manifest["job_digest"] != job_digest
    ):
        raise PageEvidenceError("page evidence manifest identity is invalid")
    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, dict) or set(artifacts) != {
        "page_tests",
        "runtime_capture",
        "visual",
    }:
        raise PageEvidenceError("page evidence artifacts are invalid")
    resolved_artifacts: list[Path] = []
    for name in ("page_tests", "runtime_capture", "visual"):
        artifact = artifacts[name]
        expected_keys = {"path", "sha256", "status"}
        if name == "runtime_capture":
            expected_keys.add("actual_source")
        if (
            not isinstance(artifact, dict)
            or set(artifact) != expected_keys
            or artifact["status"] != "passed"
            or not isinstance(artifact["sha256"], str)
            or SHA256_HEX.fullmatch(artifact["sha256"]) is None
        ):
            raise PageEvidenceError(f"{name} evidence is invalid")
        resolved_artifact = _require_state_artifact(state_root, artifact["path"])
        if hashlib.sha256(resolved_artifact.read_bytes()).hexdigest() != artifact["sha256"]:
            raise PageEvidenceError(f"{name} evidence digest is invalid")
        resolved_artifacts.append(resolved_artifact)
    runtime_capture = artifacts["runtime_capture"]
    if (
        runtime_capture["actual_source"]
        != RUNTIME_CAPTURE_SOURCES[job["platform"]]
    ):
        raise PageEvidenceError("runtime capture source is invalid")
    if len(set(resolved_artifacts)) != len(resolved_artifacts):
        raise PageEvidenceError("page evidence artifacts must be distinct")


def prepare(job_path: Path) -> dict:
    job = _load_job(job_path)
    registry_path = Path(__file__).resolve().parent.parent / "references" / "registries.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    platform = registry["platforms"].get(job["platform"])
    if platform is None or job["profile"] not in platform["profiles"]:
        raise PlatformProfileError("platform/profile pair is not registered")
    project_root = Path(job["project_root"])
    if project_root.is_symlink() or not project_root.is_dir():
        raise JobValidationError("project_root must be a real directory")
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if revision.returncode != 0 or revision.stdout.strip() != job["base_revision"]:
        raise BaseRevisionError("worktree base revision does not match the job")
    canonical_job = _canonical_bytes(job)
    job_digest = hashlib.sha256(canonical_job).hexdigest()
    state_key = hashlib.sha256(job["job_id"].encode("utf-8")).hexdigest()
    state_base = project_root / ".icp"
    page_jobs_root = state_base / "page-jobs"
    state_root = page_jobs_root / state_key
    if any(path.is_symlink() for path in (state_base, page_jobs_root, state_root)):
        raise JobValidationError("page-job state root cannot be a symlink")
    input_path = state_root / "input.json"
    resume = input_path.exists()
    state_root.mkdir(parents=True, exist_ok=True)
    if resume and input_path.read_bytes() != canonical_job:
        return {
            "kind": "icp.page-job-decision.v1",
            "schema_version": 1,
            "status": "blocked",
            "reason": "input-drift",
            "job_id": job["job_id"],
            "state_root": str(state_root),
        }
    if not resume:
        with input_path.open("xb") as handle:
            handle.write(canonical_job)
    return {
        "kind": "icp.page-job-decision.v1",
        "schema_version": 1,
        "status": "resume-required" if resume else "ready",
        "job_id": job["job_id"],
        "job_digest": job_digest,
        "state_root": str(state_root),
    }


def finalize(job_path: Path, handoff_path: Path, result_path: Path) -> dict:
    job = _load_job(job_path)
    canonical_job = _canonical_bytes(job)
    job_digest = hashlib.sha256(canonical_job).hexdigest()
    state_key = hashlib.sha256(job["job_id"].encode("utf-8")).hexdigest()
    state_base = Path(job["project_root"]) / ".icp"
    page_jobs_root = state_base / "page-jobs"
    state_root = page_jobs_root / state_key
    if (
        any(path.is_symlink() for path in (state_base, page_jobs_root, state_root))
        or not state_root.is_dir()
    ):
        raise JobValidationError("page job state path is invalid")
    input_path = state_root / "input.json"
    if (
        input_path.is_symlink()
        or not input_path.is_file()
        or input_path.read_bytes() != canonical_job
    ):
        raise JobValidationError("page job is not prepared with this input")
    handoff = _load_job_document(handoff_path)
    if set(handoff) != {
        "changed_files",
        "evidence_manifest",
        "kind",
        "schema_version",
        "status",
        "verification",
    }:
        raise JobValidationError("handoff keys do not match the contract")
    if (
        handoff["kind"] != "icp.page-handoff-input.v1"
        or handoff["schema_version"] != 1
    ):
        raise JobValidationError("handoff contract version is invalid")
    verification = handoff.get("verification")
    if (
        handoff.get("status") != "ready-for-pr"
        or not isinstance(verification, dict)
        or set(verification) != {"page_tests", "runtime_capture", "visual"}
        or any(value != "passed" for value in verification.values())
    ):
        raise PageVerificationError("page verification did not pass")
    evidence_path = Path(handoff.get("evidence_manifest", ""))
    try:
        relative_evidence = evidence_path.relative_to(state_root)
        if ".." in relative_evidence.parts:
            raise ValueError("page evidence contains parent traversal")
        resolved_evidence = evidence_path.resolve(strict=True)
        resolved_evidence.relative_to(state_root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise PageEvidenceError("page evidence is outside the job state") from exc
    if (
        evidence_path.is_symlink()
        or any(
            (state_root.joinpath(*relative_evidence.parts[:index])).is_symlink()
            for index in range(1, len(relative_evidence.parts))
        )
        or not evidence_path.is_file()
    ):
        raise PageEvidenceError("page evidence is missing")
    _validate_evidence_manifest(evidence_path, state_root, job, job_digest)
    changed_files = handoff.get("changed_files")
    if not isinstance(changed_files, list) or not changed_files:
        raise PageChangesError("changed files are missing")
    project_root = Path(job["project_root"]).resolve()
    resolved_changed_files: set[Path] = set()
    for relative in changed_files:
        if (
            not isinstance(relative, str)
            or not relative
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
        ):
            raise PageChangesError("changed file path is invalid")
        relative_path = Path(relative)
        target = project_root / relative
        try:
            resolved_target = target.resolve(strict=True)
            resolved_target.relative_to(project_root)
        except ValueError as exc:
            raise PageChangesError("changed file is outside the worktree") from exc
        except OSError as exc:
            raise PageChangesError("changed file does not exist") from exc
        if (
            target.is_symlink()
            or any(
                (project_root.joinpath(*relative_path.parts[:index])).is_symlink()
                for index in range(1, len(relative_path.parts))
            )
            or not target.is_file()
        ):
            raise PageChangesError("changed file does not exist")
        if resolved_target in resolved_changed_files:
            raise PageChangesError("changed_files contains a duplicate target")
        resolved_changed_files.add(resolved_target)
    result = {
        "kind": "icp.page-handoff-result.v1",
        "schema_version": 1,
        "job_id": job["job_id"],
        "job_digest": job_digest,
        "base_revision": job["base_revision"],
        "project_root": job["project_root"],
        "status": handoff["status"],
        "changed_files": handoff["changed_files"],
        "verification": handoff["verification"],
        "evidence_manifest": handoff["evidence_manifest"],
        "evidence_manifest_digest": hashlib.sha256(
            evidence_path.read_bytes()
        ).hexdigest(),
    }
    result_bytes = _canonical_bytes(result)
    if result_path.exists():
        if (
            result_path.is_symlink()
            or not result_path.is_file()
            or result_path.read_bytes() != result_bytes
        ):
            raise JobValidationError("existing result does not match this handoff")
        return result
    with result_path.open("xb") as handle:
        handle.write(result_bytes)
    return result


def _load_job_document(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise JobValidationError("handoff must be a JSON object")
    return document


def _emit_decision(status: str, reason: str, exit_code: int) -> int:
    print(
        json.dumps(
            {
                "kind": "icp.page-job-decision.v1",
                "schema_version": 1,
                "status": status,
                "reason": reason,
            },
            separators=(",", ":"),
        )
    )
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="icp_page_job_v1.py")
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--job", required=True, type=Path)
    finalize_parser = subparsers.add_parser("finalize")
    finalize_parser.add_argument("--job", required=True, type=Path)
    finalize_parser.add_argument("--handoff", required=True, type=Path)
    finalize_parser.add_argument("--result", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare(args.job)
        else:
            result = finalize(args.job, args.handoff, args.result)
    except PageChangesError:
        return _emit_decision("verification-failed", "page-changes-invalid", 4)
    except PageEvidenceError:
        return _emit_decision("verification-failed", "page-evidence-missing", 4)
    except PageVerificationError:
        return _emit_decision(
            "verification-failed", "page-verification-not-passed", 4
        )
    except PlatformProfileError:
        return _emit_decision("invalid-input", "unsupported-platform-profile", 2)
    except BaseRevisionError:
        return _emit_decision("invalid-input", "base-revision-mismatch", 2)
    except JobUnreadableError:
        return _emit_decision("invalid-input", "job-unreadable", 2)
    except JobValidationError:
        return _emit_decision("invalid-input", "job_schema_invalid", 2)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 3 if result["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
