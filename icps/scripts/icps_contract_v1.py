#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse


PLATFORM_PROFILES = {
    "android-java": "android-java-standard",
    "android-kotlin": "android-kotlin-standard",
    "flutter": "flutter-standard",
    "ios-objc": "ios-objc-standard",
    "ios-swift": "ios-swift-standard",
    "nextjs": "nextjs-standard",
    "vue": "vue-vite",
}

PLATFORM_ALIASES = {
    "androidjava": "android-java",
    "androidkotlin": "android-kotlin",
    "flutter": "flutter",
    "iosobjc": "ios-objc",
    "iosswift": "ios-swift",
    "nextjs": "nextjs",
    "vue": "vue",
}

SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
CLAIM_KEYS = {
    "design_ref",
    "design_source",
    "kind",
    "lease_token",
    "page",
    "row_digest",
    "row_id",
    "schema_version",
    "status",
}
PAGE_KEYS = {"acceptance_criteria", "requirement", "route", "title"}
MAPPING_KEYS = {"ignored_columns", "job", "kind", "queue", "schema_version"}
DEFAULT_MAPPING = Path(__file__).parents[1] / "references" / "column-mapping-v1.json"
DEFAULT_INTERVAL_MINUTES = 10
DEFAULT_WATCH_STATUS = "ready"
RESERVED_WATCH_STATUSES = {"doing", "done"}


def classify_excel_url(excel_url: str) -> dict[str, object]:
    if any(ord(character) < 32 or ord(character) == 127 for character in excel_url):
        raise ValueError("Excel URL contains control characters")
    parsed = urlparse(excel_url)
    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme == "https"
        and hostname == "docs.google.com"
        and parsed.path.startswith("/spreadsheets/")
    ):
        return {
            "kind": "icps.connector-selection.v1",
            "schema_version": 1,
            "provider": "google-sheets",
            "connector_family": "google-sheets",
        }
    if parsed.scheme == "https" and (
        hostname.endswith(".sharepoint.com")
        or hostname == "onedrive.live.com"
        or hostname == "1drv.ms"
    ):
        return {
            "kind": "icps.connector-selection.v1",
            "schema_version": 1,
            "provider": "microsoft-excel",
            "connector_family": "microsoft-excel",
        }
    raise ValueError("unsupported Excel URL")


def normalize_platform(platform: str) -> tuple[str, str]:
    normalized = platform.strip().lower().replace(".", "").replace("-", "")
    canonical = PLATFORM_ALIASES.get(normalized)
    if canonical is None:
        raise ValueError("unsupported ICP target platform")
    return canonical, PLATFORM_PROFILES[canonical]


def detect_platform(project_root: Path) -> tuple[str, str]:
    candidates: set[str] = set()

    pubspec = project_root / "pubspec.yaml"
    if pubspec.is_file() and "sdk: flutter" in pubspec.read_text(encoding="utf-8"):
        candidates.add("flutter")

    has_xcode_project = any(project_root.glob("*.xcodeproj/project.pbxproj"))
    if has_xcode_project and any(project_root.rglob("*.swift")):
        candidates.add("ios-swift")
    if has_xcode_project and (
        any(project_root.rglob("*.m")) or any(project_root.rglob("*.mm"))
    ):
        candidates.add("ios-objc")

    has_gradle_settings = (project_root / "settings.gradle").is_file() or (
        project_root / "settings.gradle.kts"
    ).is_file()
    if has_gradle_settings:
        build_files = [
            *project_root.rglob("build.gradle"),
            *project_root.rglob("build.gradle.kts"),
        ]
        has_android_plugin = any(
            "com.android." in build_file.read_text(encoding="utf-8")
            for build_file in build_files
        )
        if has_android_plugin and any(project_root.rglob("*.kt")):
            candidates.add("android-kotlin")
        elif has_android_plugin and any(project_root.rglob("*.java")):
            candidates.add("android-java")

    package_json = project_root / "package.json"
    if package_json.is_file():
        manifest = json.loads(package_json.read_text(encoding="utf-8"))
        dependencies = {
            **manifest.get("dependencies", {}),
            **manifest.get("devDependencies", {}),
        }
        if "next" in dependencies:
            candidates.add("nextjs")
        if "vue" in dependencies:
            candidates.add("vue")

    if not candidates:
        raise ValueError("unable to detect ICP target platform from project directory")
    if len(candidates) > 1:
        raise ValueError(
            "ambiguous ICP target platform in project directory: "
            + ", ".join(sorted(candidates))
        )
    return normalize_platform(candidates.pop())


def build_schedule_plan(
    excel_url: str,
    project_root: Path | None = None,
    im: int = DEFAULT_INTERVAL_MINUTES,
    status: str = DEFAULT_WATCH_STATUS,
) -> dict[str, object]:
    if (
        not isinstance(im, int)
        or isinstance(im, bool)
        or im <= 0
    ):
        raise ValueError("im must be a positive integer")
    if not isinstance(status, str) or not status.strip():
        raise ValueError("status must be a non-empty string")
    watch_status = status.strip()
    if watch_status in RESERVED_WATCH_STATUSES:
        raise ValueError(f"status {watch_status!r} is reserved")
    connector = classify_excel_url(excel_url)
    normalized_platform, profile = detect_platform(project_root or Path.cwd())
    prompt = (
        "Use $icps in run-once mode.\n"
        f"excel_url={json.dumps(excel_url)}\n"
        f"watch_status={json.dumps(watch_status)}\n"
        f"target_platform={normalized_platform}\n"
        f"mapping_path={json.dumps(str(DEFAULT_MAPPING))}\n"
        "process exactly one eligible row using the atomic claim, ICP, verification, "
        "PR-to-dev, and terminal writeback contract."
    )
    return {
        "kind": "icps.automation-plan.v1",
        "schema_version": 1,
        "im": im,
        "interval_seconds": im * 60,
        "rrule": f"FREQ=MINUTELY;INTERVAL={im}",
        "watch_status": watch_status,
        "excel_url": excel_url,
        "provider": connector["provider"],
        "connector_family": connector["connector_family"],
        "platform": normalized_platform,
        "profile": profile,
        "prompt": prompt,
        "mapping_path": str(DEFAULT_MAPPING),
        "required_connector_operations": (
            ["claim_ready_row", "complete_claimed_row"]
            if connector["connector_family"] == "google-sheets"
            else ["read-one", "compare-and-set-claim", "compare-and-set-done"]
        ),
    }


def read_json_object(path: str, label: str) -> dict[str, object]:
    document_path = Path(path)
    if not document_path.is_absolute() or not document_path.is_file() or document_path.is_symlink():
        raise ValueError(f"{label} must be an absolute regular non-symlink JSON file")
    try:
        document = json.loads(document_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} JSON is unreadable or invalid") from error
    if not isinstance(document, dict):
        raise ValueError(f"{label} JSON must be an object")
    return document


def required_text(row: dict[str, object], source: object, label: str) -> str:
    if isinstance(source, str) and source:
        candidates = [source]
    elif (
        isinstance(source, list)
        and source
        and all(isinstance(candidate, str) and candidate for candidate in source)
        and len(set(source)) == len(source)
    ):
        candidates = source
    else:
        raise ValueError(f"mapping source for {label} is invalid")

    present = [candidate for candidate in candidates if candidate in row]
    if len(present) > 1:
        raise ValueError(
            f"mapping source for {label} is ambiguous: {', '.join(present)}"
        )
    if not present:
        raise ValueError(
            f"row column for {label} is missing; expected one of: "
            f"{', '.join(candidates)}"
        )

    resolved_source = present[0]
    value = row.get(resolved_source)
    if not isinstance(value, (str, int)) or not str(value).strip():
        raise ValueError(f"row value for {resolved_source} is required")
    return str(value).strip()


def map_excel_row(mapping_path: str, row_path: str) -> dict[str, object]:
    mapping = read_json_object(mapping_path, "mapping")
    row = read_json_object(row_path, "row")
    if set(mapping) != MAPPING_KEYS:
        raise ValueError("mapping keys do not match the v1 contract")
    if mapping["kind"] != "icps.column-mapping.v1" or mapping["schema_version"] != 1:
        raise ValueError("mapping contract version is invalid")
    queue = mapping["queue"]
    job = mapping["job"]
    if not isinstance(queue, dict) or not isinstance(job, dict):
        raise ValueError("mapping queue and job must be objects")

    row_id = required_text(row, queue.get("row_id"), "row_id")
    raw_status = required_text(row, queue.get("status"), "status")
    status_values = queue.get("status_values")
    if not isinstance(status_values, dict) or raw_status not in status_values:
        raise ValueError("row status is not mapped")
    status = status_values[raw_status]
    if status != "doing":
        raise ValueError("mapped row must already be atomically claimed as doing")
    lease_token = required_text(row, queue.get("lease_token"), "lease_token")

    design_ref = required_text(row, job.get("design_ref"), "design_ref")
    design_source_mapping = job.get("design_source")
    if not isinstance(design_source_mapping, dict):
        raise ValueError("design_source mapping is invalid")
    design_source = required_text(
        {"constant": design_source_mapping.get("constant")},
        "constant",
        "design_source",
    )
    page_mapping = job.get("page")
    if not isinstance(page_mapping, dict):
        raise ValueError("page mapping is invalid")
    title = required_text(row, page_mapping.get("title"), "page.title")
    route = required_text(row, page_mapping.get("route"), "page.route")

    requirements: list[str] = []
    requirement_sections = job.get("requirement_sections")
    if not isinstance(requirement_sections, list):
        raise ValueError("requirement_sections mapping is invalid")
    for section in requirement_sections:
        if not isinstance(section, dict):
            raise ValueError("requirement section is invalid")
        source = section.get("source")
        label = section.get("label")
        if not isinstance(source, str) or not isinstance(label, str) or not label:
            raise ValueError("requirement section fields are invalid")
        value = row.get(source)
        if isinstance(value, str) and value.strip():
            requirements.append(f"[{label}]\n{value.strip()}")

    acceptance_criteria: list[str] = []
    acceptance_sections = job.get("acceptance_sections")
    if not isinstance(acceptance_sections, list):
        raise ValueError("acceptance_sections mapping is invalid")
    for section in acceptance_sections:
        if not isinstance(section, dict):
            raise ValueError("acceptance section is invalid")
        source = section.get("source")
        prefix = section.get("prefix")
        if not isinstance(source, str) or not isinstance(prefix, str) or not prefix:
            raise ValueError("acceptance section fields are invalid")
        value = row.get(source)
        if isinstance(value, str) and value.strip():
            acceptance_criteria.append(f"{prefix}: {value.strip()}")

    page = {
        "title": title,
        "route": route,
        "requirement": "\n\n".join(requirements),
        "acceptance_criteria": acceptance_criteria,
    }
    digest_input = {
        "row_id": row_id,
        "design_source": design_source,
        "design_ref": design_ref,
        "page": page,
    }
    row_digest = hashlib.sha256(
        json.dumps(
            digest_input,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "kind": "icps.claimed-row.v1",
        "schema_version": 1,
        "row_id": row_id,
        "status": status,
        "lease_token": lease_token,
        "row_digest": row_digest,
        "design_source": design_source,
        "design_ref": design_ref,
        "page": page,
    }


def load_claim(path: str) -> dict[str, object]:
    claim_path = Path(path)
    if not claim_path.is_absolute() or not claim_path.is_file() or claim_path.is_symlink():
        raise ValueError("claim must be an absolute regular non-symlink JSON file")
    try:
        claim = json.loads(claim_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("claim JSON is unreadable or invalid") from error
    if not isinstance(claim, dict) or set(claim) != CLAIM_KEYS:
        raise ValueError("claim keys do not match the v1 contract")
    if claim["kind"] != "icps.claimed-row.v1" or claim["schema_version"] != 1:
        raise ValueError("claim contract version is invalid")
    if claim["status"] != "doing" or not isinstance(claim["lease_token"], str) or not claim["lease_token"]:
        raise ValueError("claim must contain an active doing lease")
    if not isinstance(claim["row_id"], str) or not claim["row_id"]:
        raise ValueError("claim row_id is invalid")
    if not isinstance(claim["row_digest"], str) or not SHA256_HEX.fullmatch(claim["row_digest"]):
        raise ValueError("claim row_digest must be lowercase SHA-256")
    if not isinstance(claim["page"], dict) or set(claim["page"]) != PAGE_KEYS:
        raise ValueError("claim page keys do not match the v1 contract")
    return claim


def build_icp_job(
    excel_url: str,
    platform: str,
    project_root: str,
    base_revision: str,
    claim_path: str,
) -> dict[str, object]:
    connector = classify_excel_url(excel_url)
    normalized_platform, profile = normalize_platform(platform)
    root = Path(project_root)
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise ValueError("project_root must be an absolute non-symlink directory")
    if not base_revision:
        raise ValueError("base_revision is required")
    claim = load_claim(claim_path)
    document_key = hashlib.sha256(excel_url.encode("utf-8")).hexdigest()[:16]
    return {
        "kind": "icp.external-page-job.v1",
        "schema_version": 1,
        "job_id": f'excel:{connector["provider"]}:{document_key}:{claim["row_id"]}',
        "row_digest": claim["row_digest"],
        "project_root": str(root.resolve()),
        "base_revision": base_revision,
        "platform": normalized_platform,
        "profile": profile,
        "design_source": claim["design_source"],
        "design_ref": claim["design_ref"],
        "page": claim["page"],
    }


def build_done_writeback(claim_path: str, pr_url: str) -> dict[str, object]:
    claim = load_claim(claim_path)
    parsed = urlparse(pr_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("pr_url must be an absolute HTTP or HTTPS URL")
    return {
        "kind": "icps.row-writeback-intent.v1",
        "schema_version": 1,
        "row_id": claim["row_id"],
        "expected_status": "doing",
        "lease_token": claim["lease_token"],
        "set": {"status": "done", "pr_url": pr_url},
    }


def publish_json(document: dict[str, object], output: str) -> dict[str, object]:
    output_path = Path(output)
    if not output_path.is_absolute():
        raise ValueError("output must be an absolute path")
    if not output_path.parent.is_dir() or output_path.parent.is_symlink():
        raise ValueError("output parent must be a regular directory")
    try:
        with output_path.open("x", encoding="utf-8") as stream:
            json.dump(document, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except FileExistsError as error:
        raise ValueError("output already exists") from error
    return {"status": "written", "path": str(output_path)}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build and validate ICPS scheduler contracts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "schedule-plan --excel-url URL [--im MINUTES] [--status VALUE]\n\n"
            "defaults:\n"
            "  --im default: 10\n"
            "  --status default: ready"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    classify_parser = subparsers.add_parser("classify")
    classify_parser.add_argument("--excel-url", required=True)
    schedule_parser = subparsers.add_parser("schedule-plan")
    schedule_parser.add_argument("--excel-url", required=True)
    schedule_parser.add_argument(
        "--im",
        type=int,
        default=DEFAULT_INTERVAL_MINUTES,
    )
    schedule_parser.add_argument(
        "--status",
        default=DEFAULT_WATCH_STATUS,
    )
    build_job_parser = subparsers.add_parser("build-job")
    build_job_parser.add_argument("--excel-url", required=True)
    build_job_parser.add_argument("--platform", required=True)
    build_job_parser.add_argument("--project-root", required=True)
    build_job_parser.add_argument("--base-revision", required=True)
    build_job_parser.add_argument("--claim", required=True)
    build_job_parser.add_argument("--output")
    done_parser = subparsers.add_parser("build-done-writeback")
    done_parser.add_argument("--claim", required=True)
    done_parser.add_argument("--pr-url", required=True)
    map_row_parser = subparsers.add_parser("map-row")
    map_row_parser.add_argument("--mapping", required=True)
    map_row_parser.add_argument("--row", required=True)
    map_row_parser.add_argument("--output")
    arguments = parser.parse_args()

    if arguments.command == "classify":
        print(json.dumps(classify_excel_url(arguments.excel_url), sort_keys=True))
        return 0
    if arguments.command == "schedule-plan":
        print(
            json.dumps(
                build_schedule_plan(
                    arguments.excel_url,
                    im=arguments.im,
                    status=arguments.status,
                ),
                sort_keys=True,
            )
        )
        return 0
    if arguments.command == "map-row":
        document = map_excel_row(arguments.mapping, arguments.row)
        print(
            json.dumps(
                publish_json(document, arguments.output) if arguments.output else document,
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    if arguments.command == "build-job":
        document = build_icp_job(
            arguments.excel_url,
            arguments.platform,
            arguments.project_root,
            arguments.base_revision,
            arguments.claim,
        )
        print(
            json.dumps(
                publish_json(document, arguments.output) if arguments.output else document,
                sort_keys=True,
            )
        )
        return 0
    if arguments.command == "build-done-writeback":
        print(
            json.dumps(
                build_done_writeback(arguments.claim, arguments.pr_url),
                sort_keys=True,
            )
        )
        return 0
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as error:
        print(json.dumps({"status": "invalid-input", "reason": str(error)}))
        raise SystemExit(2)
