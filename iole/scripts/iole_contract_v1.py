#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_MAPPING = Path(__file__).parents[1] / "references" / "role-mapping-v1.json"
ICP_SKILL_PATH = "~/.agents/skills/icp/SKILL.md"
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
REVIEW_LINE = re.compile(r"^\s*(\d+)\s*[.)、]\s*(\S(?:.*\S)?)\s*$")
SOURCE_ID = re.compile(r"^(google-sheets|microsoft-excel):[0-9a-f]{64}$")
ROLE_KEY = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
SKILL_NAME = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
ERROR_CODE = re.compile(
    r"^[a-z0-9][a-z0-9._-]{0,63}(?:/[a-z0-9][a-z0-9._-]{0,63})?$"
)
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


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def read_json_object(path: Path, label: str) -> dict[str, object]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"{label} cannot be read") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON") from exc
    if not isinstance(document, dict):
        raise ValueError(f"{label} must be a JSON object")
    return document


def write_json_no_clobber(path: Path, value: object) -> None:
    if not path.is_absolute():
        raise ValueError("output path must be absolute")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
    except FileExistsError as exc:
        raise ValueError("output already exists") from exc


def load_mapping(path: Path) -> dict[str, object]:
    document = read_json_object(path, "mapping")
    if set(document) != {
        "kind",
        "schema_version",
        "common",
        "roles",
        "job",
        "ignored_columns",
    }:
        raise ValueError("mapping top-level fields are invalid")
    if document.get("kind") != "iole.role-mapping.v1" or document.get(
        "schema_version"
    ) != 1:
        raise ValueError("mapping contract version is invalid")
    common = document.get("common")
    roles = document.get("roles")
    job = document.get("job")
    if (
        not isinstance(common, dict)
        or set(common) != {"priority", "row_id"}
        or not isinstance(common.get("row_id"), str)
        or not common["row_id"]
        or (
            common.get("priority") is not None
            and (
                not isinstance(common["priority"], str)
                or not common["priority"]
            )
        )
    ):
        raise ValueError("mapping common row identity is invalid")
    if not isinstance(roles, dict) or not roles:
        raise ValueError("mapping roles are invalid")
    if not isinstance(job, dict) or set(job) != {
        "acceptance_sections",
        "design_ref",
        "design_source",
        "page",
        "requirement_sections",
    }:
        raise ValueError("mapping job is invalid")
    page = job["page"]
    design_source = job["design_source"]
    if (
        not isinstance(page, dict)
        or set(page) != {"route", "title"}
        or not isinstance(design_source, dict)
        or set(design_source) != {"constant"}
    ):
        raise ValueError("mapping job fields are invalid")
    if not isinstance(job["design_ref"], str) or not job["design_ref"]:
        raise ValueError("mapping design reference is invalid")
    if not isinstance(design_source["constant"], str) or not design_source["constant"]:
        raise ValueError("mapping design source is invalid")
    if not isinstance(page["title"], str) or not page["title"]:
        raise ValueError("mapping page title is invalid")
    route = page["route"]
    if not (
        isinstance(route, str)
        and route
        or isinstance(route, list)
        and bool(route)
        and all(isinstance(alias, str) and alias for alias in route)
    ):
        raise ValueError("mapping page route is invalid")
    for key, fields in (
        ("requirement_sections", {"label", "source"}),
        ("acceptance_sections", {"prefix", "source"}),
    ):
        sections = job[key]
        if not isinstance(sections, list) or any(
            not isinstance(section, dict)
            or set(section) != fields
            or any(
                not isinstance(section[field], str) or not section[field]
                for field in fields
            )
            for section in sections
        ):
            raise ValueError(f"mapping {key} is invalid")
    ignored_columns = document["ignored_columns"]
    if not isinstance(ignored_columns, list) or any(
        not isinstance(column, dict)
        or set(column) != {"reason", "source"}
        or any(
            not isinstance(column[field], str) or not column[field]
            for field in ("reason", "source")
        )
        for column in ignored_columns
    ):
        raise ValueError("mapping ignored columns are invalid")

    role_columns: set[str] = set()
    required_queue_keys = {
        "last_error",
        "lease_token",
        "lease_until",
        "pr_url",
        "reviews",
        "status",
        "status_values",
    }
    for role, role_config in roles.items():
        if not isinstance(role, str) or ROLE_KEY.fullmatch(role) is None:
            raise ValueError("mapping role name is invalid")
        if not isinstance(role_config, dict) or set(role_config) != {
            "queue",
            "worker_skill",
            "worker_skill_name",
        }:
            raise ValueError(f"mapping role {role} is invalid")
        worker_skill = role_config["worker_skill"]
        worker_skill_name = role_config["worker_skill_name"]
        if (worker_skill is None) != (worker_skill_name is None):
            raise ValueError(f"mapping role {role} worker name and path are inconsistent")
        if worker_skill_name is not None and (
            not isinstance(worker_skill_name, str)
            or SKILL_NAME.fullmatch(worker_skill_name) is None
        ):
            raise ValueError(f"mapping role {role} worker name is invalid")
        if worker_skill is not None and (
            not isinstance(worker_skill, str)
            or not Path(worker_skill).expanduser().is_absolute()
        ):
            raise ValueError(f"mapping role {role} worker is invalid")
        if role == "client" and (
            worker_skill_name != "icp" or worker_skill != ICP_SKILL_PATH
        ):
            raise ValueError("client-worker-must-be-icp")
        queue = role_config["queue"]
        if not isinstance(queue, dict) or set(queue) != required_queue_keys:
            raise ValueError(f"mapping role {role} queue is invalid")
        status_values = queue["status_values"]
        if not isinstance(status_values, dict) or set(status_values) != {
            "doing",
            "done",
            "ready",
            "review",
        }:
            raise ValueError(f"mapping role {role} statuses are invalid")
        columns = [queue[key] for key in required_queue_keys - {"status_values"}]
        if any(not isinstance(column, str) or not column for column in columns):
            raise ValueError(f"mapping role {role} columns are invalid")
        if len(set(columns)) != len(columns):
            raise ValueError(f"mapping role {role} columns overlap")
        overlap = role_columns.intersection(columns)
        if overlap:
            raise ValueError("mapping role columns must be independent")
        role_columns.update(columns)
        values = list(status_values.values())
        if any(not isinstance(value, str) or not value for value in values):
            raise ValueError(f"mapping role {role} status values are invalid")
        if len(set(values)) != len(values):
            raise ValueError(f"mapping role {role} status values overlap")
    return document


def build_source_id(
    provider: str, spreadsheet_id: str, sheet_name: str
) -> dict[str, object]:
    if provider not in {"google-sheets", "microsoft-excel"}:
        raise ValueError("source provider is unsupported")
    for label, value in (
        ("spreadsheet_id", spreadsheet_id),
        ("sheet_name", sheet_name),
    ):
        if not value or any(
            ord(character) < 32 or ord(character) == 127 for character in value
        ):
            raise ValueError(f"{label} must be non-empty and contain no control characters")
    digest = hashlib.sha256(
        canonical_bytes(
            {
                "sheet_name": sheet_name,
                "spreadsheet_id": spreadsheet_id,
            }
        )
    ).hexdigest()
    return {
        "kind": "iole.source-id.v1",
        "schema_version": 1,
        "source_id": f"{provider}:{digest}",
    }


def build_branch_name(source_id: str, role: str, row_id: str) -> dict[str, object]:
    if SOURCE_ID.fullmatch(source_id) is None:
        raise ValueError("source_id must be generated by source-id")
    if ROLE_KEY.fullmatch(role) is None:
        raise ValueError("branch role is invalid")
    if not row_id or any(
        ord(character) < 32 or ord(character) == 127 for character in row_id
    ):
        raise ValueError("branch row identity is invalid")
    source_digest = source_id.rsplit(":", 1)[1]
    row_digest = hashlib.sha256(row_id.encode("utf-8")).hexdigest()
    return {
        "kind": "iole.branch-name.v1",
        "schema_version": 1,
        "branch_name": (
            f"codex/iole-{source_digest[:12]}-{role}-{row_digest[:12]}"
        ),
    }


def build_pr_recovery_plan(
    source_id: str,
    role: str,
    row_id: str,
    pr_url: str,
    mr_state: str,
    source_branch: str,
    dev_revision: str,
    review_number: int,
) -> dict[str, object]:
    branch = str(build_branch_name(source_id, role, row_id)["branch_name"])
    validate_http_url(pr_url, "existing PR URL")
    if mr_state not in {"open", "merged", "closed"}:
        raise ValueError("MR state is invalid")
    if source_branch not in {"present", "missing"}:
        raise ValueError("source branch state is invalid")
    if source_branch == "present" and mr_state == "open":
        return {
            "kind": "iole.pr-recovery-plan.v1",
            "schema_version": 1,
            "action": "reuse-existing-pr",
            "base_revision": None,
            "branch_name": None,
            "existing_pr_url": pr_url,
            "mr_state": mr_state,
            "changed_action": "update-existing-pr",
            "unchanged_action": "return-to-review",
        }
    if GIT_SHA.fullmatch(dev_revision) is None:
        raise ValueError("dev revision must be a 40-character Git SHA")
    if review_number < 1:
        raise ValueError("review number must be positive")
    pr_digest = hashlib.sha256(pr_url.encode("utf-8")).hexdigest()
    return {
        "kind": "iole.pr-recovery-plan.v1",
        "schema_version": 1,
        "action": "inspect-from-dev",
        "base_revision": dev_revision.lower(),
        "branch_name": f"{branch}-recovery-{pr_digest[:8]}-r{review_number}",
        "existing_pr_url": pr_url,
        "mr_state": mr_state,
        "changed_action": "create-new-pr",
        "unchanged_action": "return-to-review",
    }


def select_role(mapping: dict[str, object], role: str) -> dict[str, object]:
    roles = mapping["roles"]
    assert isinstance(roles, dict)
    role_config = roles.get(role)
    if not isinstance(role_config, dict):
        raise ValueError("unsupported IOLE role")
    common = mapping["common"]
    assert isinstance(common, dict)
    queue = role_config["queue"]
    assert isinstance(queue, dict)
    return {
        "kind": "iole.role-config.v1",
        "schema_version": 1,
        "role": role,
        "worker_skill_name": role_config["worker_skill_name"],
        "worker_skill": role_config["worker_skill"],
        "queue": {"row_id": common["row_id"], **queue},
    }


def writeback_guard_columns(
    mapping: dict[str, object], role_config: dict[str, object]
) -> list[str]:
    job = mapping["job"]
    queue = role_config["queue"]
    assert isinstance(job, dict)
    assert isinstance(queue, dict)
    page = job["page"]
    assert isinstance(page, dict)
    columns = {
        queue["row_id"],
        job["design_ref"],
        queue["pr_url"],
        queue["reviews"],
    }
    for source in (page["title"], page["route"]):
        if isinstance(source, str):
            columns.add(source)
        else:
            columns.update(source)
    for section_name in ("requirement_sections", "acceptance_sections"):
        sections = job[section_name]
        assert isinstance(sections, list)
        columns.update(section["source"] for section in sections)
    return sorted(columns)


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
        provider = "google-sheets"
    elif parsed.scheme == "https" and (
        hostname.endswith(".sharepoint.com")
        or hostname == "onedrive.live.com"
        or hostname == "1drv.ms"
    ):
        provider = "microsoft-excel"
    else:
        raise ValueError("unsupported Excel URL")
    return {
        "kind": "iole.connector-selection.v1",
        "schema_version": 1,
        "provider": provider,
        "connector_family": provider,
    }


def normalize_platform(platform: str) -> tuple[str, str]:
    normalized = platform.strip().lower().replace(".", "").replace("-", "")
    canonical = PLATFORM_ALIASES.get(normalized)
    if canonical is None:
        raise ValueError("unsupported client target platform")
    return canonical, PLATFORM_PROFILES[canonical]


def detect_client_platform(project_root: Path) -> tuple[str, str]:
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
        manifest = read_json_object(package_json, "package.json")
        declared_dependencies = manifest.get("dependencies", {})
        declared_dev_dependencies = manifest.get("devDependencies", {})
        if not isinstance(declared_dependencies, dict) or not isinstance(
            declared_dev_dependencies, dict
        ):
            raise ValueError("package.json dependency sections must be objects")
        dependencies = {
            **declared_dependencies,
            **declared_dev_dependencies,
        }
        if "next" in dependencies:
            candidates.add("nextjs")
        if "vue" in dependencies:
            candidates.add("vue")

    if not candidates:
        raise ValueError("unable to detect client target platform")
    if len(candidates) > 1:
        raise ValueError("ambiguous client target platform: " + ", ".join(sorted(candidates)))
    return normalize_platform(candidates.pop())


def build_schedule_plan(
    excel_url: str,
    role: str,
    im: int,
    mr: int,
    project_root: Path,
    mapping_path: Path,
) -> dict[str, object]:
    if im <= 0:
        raise ValueError("im must be a positive integer")
    if mr not in {0, 1, 2}:
        raise ValueError("mr must be 0, 1, or 2")
    selection = classify_excel_url(excel_url)
    mapping = load_mapping(mapping_path)
    role_config = select_role(mapping, role)
    worker_skill = role_config["worker_skill"]
    if not isinstance(worker_skill, str) or not Path(worker_skill).expanduser().is_file():
        raise ValueError("role-worker-unavailable")
    platform = None
    profile = None
    if role == "client":
        platform, profile = detect_client_platform(project_root)
    queue = role_config["queue"]
    assert isinstance(queue, dict)
    status_values = queue["status_values"]
    assert isinstance(status_values, dict)
    prompt_payload = {
        "excel_url": excel_url,
        "mapping_path": str(mapping_path.resolve()),
        "project_root": str(project_root.resolve()),
        "role": role,
        "mr": mr,
    }
    return {
        "kind": "iole.schedule-plan.v1",
        "schema_version": 1,
        "document_digest": hashlib.sha256(excel_url.encode("utf-8")).hexdigest(),
        "role": role,
        "mr": mr,
        "provider": selection["provider"],
        "connector_family": selection["connector_family"],
        "mapping_path": str(mapping_path.resolve()),
        "project_root": str(project_root.resolve()),
        "platform": platform,
        "profile": profile,
        "worker_skill_name": role_config["worker_skill_name"],
        "worker_skill": worker_skill,
        "role_queue": queue,
        "connector_queue": {
            "row_id": queue["row_id"],
            "status": queue["status"],
            "lease_token": queue["lease_token"],
            "lease_until": queue["lease_until"],
            "pr_url": queue["pr_url"],
            "ready": status_values["ready"],
            "doing": status_values["doing"],
            "done": status_values["review"],
        },
        "required_connector_operations": [
            "claim_ready_row",
            "complete_claimed_row",
        ],
        "rrule": f"FREQ=MINUTELY;INTERVAL={im}",
        "prompt": "Use $iole run-once with "
        + json.dumps(prompt_payload, ensure_ascii=False, sort_keys=True),
    }


def text_value(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def resolve_source(row: dict[str, object], source: object, label: str) -> str:
    if isinstance(source, str):
        return text_value(row.get(source))
    if not isinstance(source, list) or not source or not all(
        isinstance(item, str) and item for item in source
    ):
        raise ValueError(f"mapping {label} source is invalid")
    present = [item for item in source if item in row]
    if len(present) != 1:
        raise ValueError(f"row {label} alias is missing or ambiguous")
    return text_value(row.get(present[0]))


def compose_sections(
    row: dict[str, object], sections: object, prefix_key: str
) -> list[str]:
    if not isinstance(sections, list):
        raise ValueError("mapping sections are invalid")
    result: list[str] = []
    for section in sections:
        if not isinstance(section, dict):
            raise ValueError("mapping section is invalid")
        source = section.get("source")
        prefix = section.get(prefix_key)
        if not isinstance(source, str) or not isinstance(prefix, str):
            raise ValueError("mapping section fields are invalid")
        value = text_value(row.get(source))
        if value:
            result.append(f"{prefix}: {value}")
    return result


def parse_latest_review(value: object) -> dict[str, object] | None:
    raw = text_value(value)
    if not raw:
        return None
    parsed: list[tuple[int, str]] = []
    previous = 0
    for line in raw.splitlines():
        if not line.strip():
            continue
        match = REVIEW_LINE.fullmatch(line)
        if match is None:
            raise ValueError("reviews must contain one numbered opinion per line")
        number = int(match.group(1))
        if number <= previous:
            raise ValueError("review numbers must be strictly increasing")
        previous = number
        parsed.append((number, match.group(2)))
    if not parsed:
        return None
    number, text = parsed[-1]
    return {"number": number, "text": text}


def validate_http_url(value: str, label: str) -> None:
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{label} must not contain control characters")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{label} must be an absolute HTTP or HTTPS URL")


def map_row(
    mapping_path: Path,
    role: str,
    source_id: str,
    row_path: Path,
    output_path: Path,
) -> dict[str, object]:
    if SOURCE_ID.fullmatch(source_id) is None:
        raise ValueError("source_id must be generated by source-id")
    mapping = load_mapping(mapping_path)
    role_config = select_role(mapping, role)
    row = read_json_object(row_path, "row")
    queue = role_config["queue"]
    assert isinstance(queue, dict)
    status_values = queue["status_values"]
    assert isinstance(status_values, dict)
    if text_value(row.get(queue["status"])) != status_values["doing"]:
        raise ValueError("row is not claimed for this role")
    row_id = text_value(row.get(queue["row_id"]))
    lease_token = text_value(row.get(queue["lease_token"]))
    if not row_id or not lease_token:
        raise ValueError("claimed row identity or lease is missing")

    job_mapping = mapping["job"]
    assert isinstance(job_mapping, dict)
    page_mapping = job_mapping.get("page")
    if not isinstance(page_mapping, dict):
        raise ValueError("mapping page is invalid")
    design_source_mapping = job_mapping.get("design_source")
    if not isinstance(design_source_mapping, dict) or not isinstance(
        design_source_mapping.get("constant"), str
    ):
        raise ValueError("mapping design source is invalid")
    design_ref_source = job_mapping.get("design_ref")
    if not isinstance(design_ref_source, str):
        raise ValueError("mapping design reference is invalid")
    design_ref = text_value(row.get(design_ref_source))
    title = resolve_source(row, page_mapping.get("title"), "title")
    route = resolve_source(row, page_mapping.get("route"), "route")
    requirements = compose_sections(
        row, job_mapping.get("requirement_sections"), "label"
    )
    acceptance = compose_sections(
        row, job_mapping.get("acceptance_sections"), "prefix"
    )
    missing_fields = []
    if not design_ref:
        missing_fields.append("设计稿地址")
    if not title:
        missing_fields.append("标题")
    if not route:
        missing_fields.append("页面路由/Route")
    if not requirements:
        missing_fields.append("UI补充描述/交互描述/接口描述")
    if missing_fields:
        raise ValueError("missing required fields: " + ", ".join(missing_fields))
    latest_review = parse_latest_review(row.get(queue["reviews"]))
    existing_pr_url = text_value(row.get(queue["pr_url"])) or None
    if existing_pr_url is not None:
        validate_http_url(existing_pr_url, "existing PR URL")
    if existing_pr_url is not None and latest_review is None:
        raise ValueError("an existing PR URL requires a numbered review")
    page = {
        "title": title,
        "route": route,
        "requirement": "\n".join(requirements),
        "acceptance_criteria": acceptance,
    }
    immutable = {
        "source_id": source_id,
        "row_id": row_id,
        "role": role,
        "design_source": design_source_mapping["constant"],
        "design_ref": design_ref,
        "page": page,
        "latest_review": latest_review,
    }
    claim = {
        "kind": "iole.claimed-row.v1",
        "schema_version": 1,
        "source_id": source_id,
        "role": role,
        "row_id": row_id,
        "status": "doing",
        "lease_token": lease_token,
        "lease_until": text_value(row.get(queue["lease_until"])),
        "row_digest": hashlib.sha256(canonical_bytes(immutable)).hexdigest(),
        "existing_pr_url": existing_pr_url,
        "latest_review": latest_review,
        "design_source": design_source_mapping["constant"],
        "design_ref": design_ref,
        "page": page,
    }
    write_json_no_clobber(output_path, claim)
    return claim


def load_claim(path: Path) -> dict[str, object]:
    claim = read_json_object(path, "claim")
    required = {
        "design_ref",
        "design_source",
        "existing_pr_url",
        "kind",
        "latest_review",
        "lease_token",
        "page",
        "role",
        "row_digest",
        "row_id",
        "schema_version",
        "source_id",
        "status",
    }
    allowed = required | {"lease_until"}
    if not required.issubset(claim) or not set(claim).issubset(allowed):
        raise ValueError("claim keys do not match the v1 contract")
    if claim["kind"] != "iole.claimed-row.v1" or claim["schema_version"] != 1:
        raise ValueError("claim contract version is invalid")
    if (
        claim["status"] != "doing"
        or not isinstance(claim["lease_token"], str)
        or not claim["lease_token"]
    ):
        raise ValueError("claim ownership is invalid")
    if not isinstance(claim["role"], str) or not claim["role"]:
        raise ValueError("claim role is invalid")
    if (
        not isinstance(claim["source_id"], str)
        or SOURCE_ID.fullmatch(claim["source_id"]) is None
    ):
        raise ValueError("claim source identity is invalid")
    if not isinstance(claim["row_id"], str) or not claim["row_id"]:
        raise ValueError("claim row identity is invalid")
    if not isinstance(claim["design_source"], str) or not claim["design_source"]:
        raise ValueError("claim design source is invalid")
    if not isinstance(claim["design_ref"], str) or not claim["design_ref"]:
        raise ValueError("claim design reference is invalid")
    if not isinstance(claim["page"], dict):
        raise ValueError("claim page is invalid")
    existing_pr_url = claim["existing_pr_url"]
    if existing_pr_url is not None:
        if not isinstance(existing_pr_url, str):
            raise ValueError("claim existing PR URL is invalid")
        validate_http_url(existing_pr_url, "existing PR URL")
    review = claim["latest_review"]
    if review is not None and (
        not isinstance(review, dict)
        or set(review) != {"number", "text"}
        or type(review["number"]) is not int
        or review["number"] <= 0
        or not isinstance(review["text"], str)
        or not review["text"].strip()
    ):
        raise ValueError("claim review is invalid")
    if (review is None) != (existing_pr_url is None):
        raise ValueError("claim review and existing PR URL are inconsistent")
    if not isinstance(claim["row_digest"], str) or not SHA256_HEX.fullmatch(
        claim["row_digest"]
    ):
        raise ValueError("claim row digest is invalid")
    immutable = {
        "source_id": claim["source_id"],
        "row_id": claim["row_id"],
        "role": claim["role"],
        "design_source": claim["design_source"],
        "design_ref": claim["design_ref"],
        "page": claim["page"],
        "latest_review": review,
    }
    actual_digest = hashlib.sha256(canonical_bytes(immutable)).hexdigest()
    if actual_digest != claim["row_digest"]:
        raise ValueError("claim digest mismatch")
    return claim


def build_job(
    claim_path: Path,
    worktree: Path,
    base_revision: str,
    platform_input: str,
    output_path: Path,
) -> dict[str, object]:
    claim = load_claim(claim_path)
    if claim["role"] != "client":
        raise ValueError("ICP accepts only the client role")
    if not worktree.is_absolute() or not worktree.is_dir():
        raise ValueError("worktree must be an existing absolute directory")
    if not GIT_SHA.fullmatch(base_revision):
        raise ValueError("base revision must be a Git SHA-1")
    platform, profile = normalize_platform(platform_input)
    review = claim["latest_review"]
    if review is None:
        mode = "implement"
        review_number = 0
    elif (
        isinstance(review, dict)
        and type(review.get("number")) is int
        and review["number"] > 0
        and isinstance(review.get("text"), str)
        and review["text"].strip()
    ):
        mode = "revise"
        review_number = review["number"]
    else:
        raise ValueError("claim review is invalid")
    job = {
        "kind": "icp.external-page-job.v2",
        "schema_version": 2,
        "job_id": (
            "iole:client:"
            f"source-{hashlib.sha256(str(claim['source_id']).encode('utf-8')).hexdigest()[:12]}:"
            f"row-{claim['row_id']}:review-{review_number}:"
            f"{str(claim['row_digest'])[:12]}"
        ),
        "row_digest": claim["row_digest"],
        "project_root": str(worktree.resolve()),
        "base_revision": base_revision.lower(),
        "platform": platform,
        "profile": profile,
        "design_source": claim["design_source"],
        "design_ref": claim["design_ref"],
        "role": "client",
        "mode": mode,
        "review": review,
        "page": claim["page"],
    }
    write_json_no_clobber(output_path, job)
    return job


def build_review_writeback(
    mapping_path: Path,
    claim_path: Path,
    mr: int,
    pr_url: str | None,
) -> dict[str, object]:
    if mr not in {0, 1, 2}:
        raise ValueError("mr must be 0, 1, or 2")
    if mr == 2:
        if pr_url is None:
            raise ValueError("mr=2 requires a PR URL")
        validate_http_url(pr_url, "PR URL")
    elif pr_url is not None:
        raise ValueError("PR URL is allowed only when mr=2")
    claim = load_claim(claim_path)
    mapping = load_mapping(mapping_path)
    role_config = select_role(mapping, str(claim["role"]))
    queue = role_config["queue"]
    assert isinstance(queue, dict)
    status_values = queue["status_values"]
    assert isinstance(status_values, dict)
    return {
        "kind": "iole.role-writeback-intent.v1",
        "schema_version": 1,
        "mr": mr,
        "role": claim["role"],
        "row_id": claim["row_id"],
        "expected_row_digest": claim["row_digest"],
        "guard_columns": writeback_guard_columns(mapping, role_config),
        "expected_status": status_values["doing"],
        "lease_token": claim["lease_token"],
        "columns": {
            "status": queue["status"],
            "pr_url": queue["pr_url"],
            "lease_token": queue["lease_token"],
            "lease_until": queue["lease_until"],
            "last_error": queue["last_error"],
        },
        "set": {
            "status": status_values["review"],
            "pr_url": pr_url,
            "lease_token": "",
            "lease_until": "",
            "last_error": "",
        },
    }


def build_error_writeback(
    mapping_path: Path,
    claim_path: Path,
    error_code: str,
    error_detail: str | None = None,
) -> dict[str, object]:
    if ERROR_CODE.fullmatch(error_code) is None:
        raise ValueError("error code is invalid")
    detail = "" if error_detail is None else error_detail.strip()
    if detail and not detail.isprintable():
        raise ValueError("error detail must be one printable line")
    last_error = error_code if not detail else f"{error_code}: {detail}"
    if len(last_error) > 129:
        raise ValueError("combined error code and detail exceed 129 characters")
    claim = load_claim(claim_path)
    mapping = load_mapping(mapping_path)
    role_config = select_role(mapping, str(claim["role"]))
    queue = role_config["queue"]
    assert isinstance(queue, dict)
    status_values = queue["status_values"]
    assert isinstance(status_values, dict)
    return {
        "kind": "iole.role-error-writeback-intent.v1",
        "schema_version": 1,
        "role": claim["role"],
        "row_id": claim["row_id"],
        "expected_row_digest": claim["row_digest"],
        "guard_columns": writeback_guard_columns(mapping, role_config),
        "expected_status": status_values["doing"],
        "lease_token": claim["lease_token"],
        "columns": {
            "status": queue["status"],
            "lease_token": queue["lease_token"],
            "last_error": queue["last_error"],
        },
        "set": {"last_error": last_error},
        "orchestrator_action": {
            "notify_user_immediately": True,
            "stop_current_run": True,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="$iole",
        description="Role-aware engineering loop contract",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    source_parser = subparsers.add_parser("source-id")
    source_parser.add_argument("--provider", required=True)
    source_parser.add_argument("--spreadsheet-id", required=True)
    source_parser.add_argument("--sheet-name", required=True)

    branch_parser = subparsers.add_parser("branch-name")
    branch_parser.add_argument("--source-id", required=True)
    branch_parser.add_argument("--role", required=True)
    branch_parser.add_argument("--row-id", required=True)

    recovery_parser = subparsers.add_parser("pr-recovery-plan")
    recovery_parser.add_argument("--source-id", required=True)
    recovery_parser.add_argument("--role", required=True)
    recovery_parser.add_argument("--row-id", required=True)
    recovery_parser.add_argument("--pr-url", required=True)
    recovery_parser.add_argument("--mr-state", required=True)
    recovery_parser.add_argument("--source-branch", required=True)
    recovery_parser.add_argument("--dev-revision", required=True)
    recovery_parser.add_argument("--review-number", required=True, type=int)

    role_parser = subparsers.add_parser("role-config")
    role_parser.add_argument("--mapping", required=True)
    role_parser.add_argument("--role", required=True)

    schedule_parser = subparsers.add_parser("schedule-plan")
    schedule_parser.add_argument("--excel-url", required=True)
    schedule_parser.add_argument("--role", required=True)
    schedule_parser.add_argument("--im", type=int, default=10)
    schedule_parser.add_argument("--mr", type=int, default=0)
    schedule_parser.add_argument("--project-root", default=str(Path.cwd()))
    schedule_parser.add_argument("--mapping", default=str(DEFAULT_MAPPING))

    map_parser = subparsers.add_parser("map-row")
    map_parser.add_argument("--mapping", required=True)
    map_parser.add_argument("--role", required=True)
    map_parser.add_argument("--source-id", required=True)
    map_parser.add_argument("--row", required=True)
    map_parser.add_argument("--output", required=True)

    job_parser = subparsers.add_parser("build-job")
    job_parser.add_argument("--claim", required=True)
    job_parser.add_argument("--worktree", required=True)
    job_parser.add_argument("--base-revision", required=True)
    job_parser.add_argument("--platform", required=True)
    job_parser.add_argument("--output", required=True)

    writeback_parser = subparsers.add_parser("build-review-writeback")
    writeback_parser.add_argument("--mapping", required=True)
    writeback_parser.add_argument("--claim", required=True)
    writeback_parser.add_argument("--mr", type=int, default=0)
    writeback_parser.add_argument("--pr-url")

    error_parser = subparsers.add_parser("build-error-writeback")
    error_parser.add_argument("--mapping", required=True)
    error_parser.add_argument("--claim", required=True)
    error_parser.add_argument("--error-code", required=True)
    error_parser.add_argument("--error-detail")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "source-id":
            result = build_source_id(
                arguments.provider,
                arguments.spreadsheet_id,
                arguments.sheet_name,
            )
        elif arguments.command == "branch-name":
            result = build_branch_name(
                arguments.source_id,
                arguments.role,
                arguments.row_id,
            )
        elif arguments.command == "pr-recovery-plan":
            result = build_pr_recovery_plan(
                arguments.source_id,
                arguments.role,
                arguments.row_id,
                arguments.pr_url,
                arguments.mr_state,
                arguments.source_branch,
                arguments.dev_revision,
                arguments.review_number,
            )
        elif arguments.command == "role-config":
            result = select_role(
                load_mapping(Path(arguments.mapping)), arguments.role
            )
        elif arguments.command == "schedule-plan":
            result = build_schedule_plan(
                arguments.excel_url,
                arguments.role,
                arguments.im,
                arguments.mr,
                Path(arguments.project_root),
                Path(arguments.mapping),
            )
        elif arguments.command == "map-row":
            result = map_row(
                Path(arguments.mapping),
                arguments.role,
                arguments.source_id,
                Path(arguments.row),
                Path(arguments.output),
            )
        elif arguments.command == "build-job":
            result = build_job(
                Path(arguments.claim),
                Path(arguments.worktree),
                arguments.base_revision,
                arguments.platform,
                Path(arguments.output),
            )
        elif arguments.command == "build-review-writeback":
            result = build_review_writeback(
                Path(arguments.mapping),
                Path(arguments.claim),
                arguments.mr,
                arguments.pr_url,
            )
        else:
            result = build_error_writeback(
                Path(arguments.mapping),
                Path(arguments.claim),
                arguments.error_code,
                arguments.error_detail,
            )
    except (OSError, ValueError) as exc:
        error_payload = {"status": "invalid-input", "reason": str(exc)}
        if arguments.command == "map-row" and isinstance(exc, ValueError):
            error_payload = {
                "status": "invalid-input",
                "reason": "invalid-row-data",
                "detail": str(exc),
            }
        print(
            json.dumps(
                error_payload,
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    if arguments.command not in {"map-row", "build-job"}:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
