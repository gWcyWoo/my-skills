#!/usr/bin/env python3
"""ICP entry preflight: recover first, report missing inputs, never claim a new row."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

import csv_task_source
import entry_readiness_v1
import freeze_selection_manifest
import orchestrate_client_project_v1 as orchestrator
import platform_package_resolver_v1 as package_resolver
import resolve_run_config


HERE = Path(__file__).resolve().parent
ICP_ROOT = HERE.parent
REGISTRY_PATH = ICP_ROOT / "references" / "registries.json"
PACKAGE_INDEX_PATH = ICP_ROOT / "references" / "platform_packages_v1.json"
PLATFORMS_ROOT = HERE / "platforms"


class EntryPreflightError(ValueError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise EntryPreflightError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EntryPreflightError(f"invalid JSON document: {path}") from exc
    if not isinstance(value, dict):
        raise EntryPreflightError(f"JSON document must be an object: {path}")
    return value


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _load_module(basename: str, expected_sha256: str):
    if Path(basename).name != basename or not basename.endswith(".py"):
        raise EntryPreflightError("unsafe platform module basename")
    path = PLATFORMS_ROOT / basename
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise EntryPreflightError("platform module is not a regular file")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise EntryPreflightError("platform module digest drift")
    spec = importlib.util.spec_from_file_location(f"icp_entry_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise EntryPreflightError("platform module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _resolve_package(resolved: dict, registry: dict) -> tuple[dict, dict, dict]:
    index = _load_json(PACKAGE_INDEX_PATH)
    package_resolver.verify_package_index(index)
    profile_id = resolved.get("profile") or registry["platforms"][resolved["platform"]]["default_profile"]
    row = next(
        (
            item
            for item in index["packages"]
            if item["platform_id"] == resolved["platform"] and item["profile_id"] == profile_id
        ),
        None,
    )
    if row is None:
        raise EntryPreflightError("no fixed platform package matches platform/profile")
    package_module = _load_module(row["package_module_basename"], row["package_module_sha256"])
    descriptor = package_module.describe_package()
    verification = package_module.verify_package()
    resolution = package_resolver.resolve_package(
        platform_id=resolved["platform"],
        profile_id=profile_id,
        registries=registry,
        package_index=index,
        package_descriptor=descriptor,
        package_module_bytes=(PLATFORMS_ROOT / row["package_module_basename"]).read_bytes(),
    )
    return descriptor, verification, resolution


def _missing(id_: str, owner: str, remediation: str, detail: str) -> dict:
    return {"id": id_, "owner": owner, "remediation": remediation, "detail": detail}


def _observation(
    probe_id: str,
    status: str,
    *,
    evidence_digest: str | None = None,
    reason_code: str | None = None,
    blocked_by: list[str] | None = None,
) -> dict:
    return {
        "kind": "icp.entry-readiness-observation.v1",
        "schema_version": 1,
        "probe_id": probe_id,
        "status": status,
        "evidence_digest": evidence_digest,
        "reason_code": reason_code,
        "blocked_by": [] if blocked_by is None else list(blocked_by),
    }


def _readiness_documents(
    *,
    resolved: dict,
    descriptor: dict,
    probe: dict | None,
    task_write_probe: dict | None,
    candidates: list[dict],
    design_probe: dict | None,
    platform_report: dict | None,
    platform_missing: list[dict],
    task_source_blocked: bool = False,
    active_context: dict | None = None,
) -> tuple[dict, dict]:
    passed = hashlib.sha256(b"icp.entry-readiness.pass.v1").hexdigest()
    observations = [
        _observation(
            "core.design_source.access",
            "pass" if design_probe is not None or not candidates else "missing",
            evidence_digest=(
                hashlib.sha256(_canonical(design_probe)).hexdigest()
                if design_probe is not None
                else passed if not candidates else None
            ),
            reason_code=None if design_probe is not None or not candidates else "design_source_unavailable",
        ),
        _observation("core.project_root.access", "pass", evidence_digest=passed),
        _observation(
            "core.state_root.atomic_write",
            "pass" if task_write_probe is not None else "missing",
            evidence_digest=(
                task_write_probe["evidence_digest"] if task_write_probe is not None else None
            ),
            reason_code=None if task_write_probe is not None else "atomic_write_unavailable",
        ),
        _observation(
            "core.task_source.access",
            "blocked" if task_source_blocked else "pass" if probe is not None else "missing",
            evidence_digest=(
                None if task_source_blocked else probe["sha256"] if probe is not None else None
            ),
            reason_code=(
                "orphan_doing_without_state"
                if task_source_blocked
                else None if probe is not None else "task_source_unavailable"
            ),
        ),
    ]
    missing_requirement_ids = {item["id"] for item in platform_missing}
    descriptor_requirement_ids = {item["id"] for item in descriptor["entry_requirements"]}
    inspection_failed = bool(missing_requirement_ids - descriptor_requirement_ids)
    platform_config_digest = None
    if platform_report is not None:
        platform_config_digest = platform_report.get("platform_config_digest")
        if platform_config_digest is None and isinstance(platform_report.get("runtime_target"), dict):
            platform_config_digest = platform_report["runtime_target"].get("platform_config_digest")
    for requirement in descriptor["entry_requirements"]:
        requirement_missing = inspection_failed or requirement["id"] in missing_requirement_ids
        requirement_evidence = (
            platform_config_digest
            if requirement["id"] == "runtime_config" and platform_config_digest is not None
            else hashlib.sha256(_canonical(platform_report)).hexdigest()
            if platform_report is not None
            else None if requirement_missing else passed
        )
        observations.append(
            _observation(
                requirement["probe_id"],
                "missing" if requirement_missing else "pass",
                evidence_digest=requirement_evidence,
                reason_code="platform_requirement_missing" if requirement_missing else None,
            )
        )
    observations.sort(key=lambda item: item["probe_id"])
    task_digest = probe["sha256"] if probe is not None else hashlib.sha256(b"").hexdigest()
    candidate_digest = hashlib.sha256(_canonical(candidates)).hexdigest()
    report = entry_readiness_v1.aggregate_readiness(
        resolved_config_digest=hashlib.sha256(_canonical(resolved)).hexdigest(),
        package_descriptor=descriptor,
        task_source_id=resolved["task_source"],
        design_source_id=resolved["design_source"],
        task_source_snapshot_digest=task_digest,
        candidate_identity_digest=candidate_digest,
        candidate_count=len(candidates),
        observations=observations,
    )
    context = active_context or {
        "active_pointers": [],
        "progress": None,
        "receipts": [],
        "expected_identities": {
            "requirement_id": passed,
            "selection_manifest_digest": passed,
            "row_identity_digest": passed,
            "claim_intent_digest": passed,
            "claim_ack_digest": passed,
            "progress_id": passed,
            "verified_operation_plan_digest": passed,
        },
        "observed_row_status": "empty" if candidates else "unknown",
    }
    decision = entry_readiness_v1.decide_entry(
        readiness_report=report,
        active_pointers=context["active_pointers"],
        progress=context["progress"],
        receipts=context["receipts"],
        expected_identities=context["expected_identities"],
        exclusive_lock_acquired=True,
        observed_row_status=context["observed_row_status"],
    )
    return report, decision


def _platform_preflight(
    resolved: dict, descriptor: dict
) -> tuple[dict | None, list[dict], dict | None]:
    component = next(item for item in descriptor["components"] if item["role"] == "project_preflight")
    module = _load_module(component["module_basename"], component["module_sha256"])
    try:
        inspection = module.inspect_entry_requirements(resolved["project_root"])
    except Exception:
        return None, [
            _missing(
                "platform_project_preflight",
                "environment",
                "repair the selected platform package preflight",
                "selected platform entry inspection failed",
            )
        ], None
    if inspection.get("platform_id") != resolved["platform"]:
        return None, [
            _missing(
                "platform_project_preflight",
                "environment",
                "repair the selected platform package preflight",
                "selected platform inspection identity mismatch",
            )
        ], None
    return (
        inspection.get("platform_report"),
        list(inspection.get("missing_inputs", [])),
        inspection,
    )


def _active_status(
    store: orchestrator.RequirementStateStore, prerequisites_status: str
) -> dict | None:
    recovered = orchestrator.recover_pending_csv_claim(store)
    snapshot = store.load_snapshot()
    active = snapshot["active"]
    if active is None:
        if recovered["decision"] == "no-pending-claim":
            return None
        return {"decision": recovered["decision"], "recovery": recovered}
    scope = store.load_execution_scope(active["requirement_id"])
    intent_path = store.state_root / "claim-intents" / f"{active['requirement_id']}.json"
    intent = store._read_json(intent_path)
    observation = csv_task_source.recover_claim_with_intent(
        scope["task_ref"], scope["row_identity"], intent
    )["recovery_report"]
    observed = observation["observed_status"]
    decision = orchestrator.decide_stored_resume(
        store,
        prerequisites_status=prerequisites_status,
        observed_row_status=observed,
    )
    entry_context = {
        "active_pointers": [active],
        "progress": snapshot["progress"],
        "receipts": snapshot["receipts"],
        "expected_identities": {
            "requirement_id": scope["requirement_id"],
            "selection_manifest_digest": scope["selection_manifest_digest"],
            "row_identity_digest": intent["row_identity_digest"],
            "claim_intent_digest": hashlib.sha256(_canonical(intent)).hexdigest(),
            "claim_ack_digest": active["claim_ack_digest"],
            "progress_id": active["progress_id"],
            "verified_operation_plan_digest": scope["verified_operation_plan_digest"],
        },
        "observed_row_status": observed,
    }
    if decision.get("decision") == "needs-user-input":
        return {
            "decision": "needs-user-input",
            "resume_decision": decision,
            "_entry_context": entry_context,
        }
    if decision.get("decision") == "blocked":
        return {
            "decision": "blocked",
            "resume_decision": decision,
            "_entry_context": entry_context,
        }
    return {
        "decision": "resume-required",
        "resume_decision": decision,
        "_entry_context": entry_context,
    }


def preflight(config_path: Path) -> dict:
    config_path = config_path.expanduser().resolve(strict=True)
    config = _load_json(config_path)
    registry = _load_json(REGISTRY_PATH)
    resolved = resolve_run_config.resolve_config(config, config_path.parent, registry)
    descriptor, package_verification, resolution = _resolve_package(resolved, registry)
    platform_report, missing, platform_inspection = _platform_preflight(resolved, descriptor)
    platform_missing = list(missing)
    task_ref = Path(resolved["task_ref"])
    try:
        probe = csv_task_source.probe(task_ref)
        candidates = []
    except Exception:
        probe = None
        candidates = []
        missing.append(
            _missing(
                "task_source",
                "user",
                "supply a valid writable CSV task source",
                "task source access or schema validation failed",
            )
        )
    task_write_probe = None
    if probe is not None:
        try:
            task_write_probe = csv_task_source.probe_write_readiness(task_ref)
        except Exception:
            missing.append(
                _missing(
                    "task_source_atomic_write",
                    "user+environment",
                    "make the CSV directory support atomic create, replace, fsync, and cleanup",
                    "task source directory atomic-write probe failed",
                )
            )
    if task_ref.exists() and not os.access(task_ref, os.W_OK):
        missing.append(
            _missing(
                "task_source_writable",
                "user",
                "grant write permission to the CSV",
                "task source is not writable",
            )
        )
    state_root, _ = freeze_selection_manifest.derive_roots(
        resolved["platform"], resolved["project_root"], "entry-status"
    )
    store_path = state_root / "icp-requirements-v1"
    package_ready = resolution["activation_state"] == "active" and resolution["executable"] is True
    active_status = None
    if store_path.exists() or store_path.is_symlink():
        store = orchestrator.RequirementStateStore(store_path)
        prerequisites_status = "blocked" if not package_ready else ("missing" if missing else "met")
        with store.exclusive_lock():
            active_status = _active_status(store, prerequisites_status)
    orphan_doing = (
        active_status is None
        and probe is not None
        and probe["statuses"].get("doing", 0) > 0
    )
    if active_status is None and probe is not None and not orphan_doing:
        try:
            candidates = csv_task_source.select_candidates(task_ref, 1)
        except Exception:
            probe = None
            missing.append(
                _missing(
                    "task_source",
                    "user",
                    "repair the CSV task source",
                    "task candidate selection failed",
                )
            )
    no_work = probe is not None and not candidates and active_status is None and not orphan_doing
    if no_work:
        missing = []
    design_probe = None
    if candidates:
        try:
            from design_sources import lanhu_figma_v1

            design_probe = lanhu_figma_v1.probe(candidates[0]["design_url"])
        except Exception:
            missing.append(
                _missing(
                    "design_source_locator",
                    "user",
                    "supply an accessible Lanhu/Figma design URL for the next row",
                    "design source locator validation or access failed",
                )
            )
    readiness_report, entry_gate_decision = _readiness_documents(
        resolved=resolved,
        descriptor=descriptor,
        probe=probe,
        task_write_probe=task_write_probe,
        candidates=candidates,
        design_probe=design_probe,
        platform_report=platform_report,
        platform_missing=[] if no_work else platform_missing,
        task_source_blocked=orphan_doing,
        active_context=(
            active_status.get("_entry_context") if active_status is not None else None
        ),
    )
    active = active_status
    if not package_ready:
        missing.append(
            _missing(
                "platform_package_activation",
                "user",
                "approve a separate audited activation diff for this platform/profile",
                f"{resolution['platform_id']}/{resolution['profile_id']} is inactive",
            )
        )
    if active is not None and active.get("decision") == "needs-user-input":
        status = "needs-user-input"
    elif active is not None and active.get("decision") == "blocked":
        status = "blocked"
    elif active is not None:
        status = "resume-required"
    elif orphan_doing:
        status = "blocked"
    elif any(item["id"] != "platform_package_activation" for item in missing):
        status = "needs-user-input"
    elif not package_ready:
        status = "blocked"
    elif no_work:
        status = "no-work"
    else:
        status = "ready"
    active_public = (
        {key: value for key, value in active.items() if key != "_entry_context"}
        if active is not None
        else None
    )
    return {
        "kind": "icp.entry-preflight-result.v1",
        "schema_version": 1,
        "status": status,
        "unattended_ready": status in {"ready", "resume-required"},
        "readiness_report": readiness_report,
        "entry_gate_decision": entry_gate_decision,
        "resolved_config": resolved,
        "package_resolution": resolution,
        "package_verification_digest": hashlib.sha256(_canonical(package_verification)).hexdigest(),
        "task_probe": probe,
        "task_write_probe": task_write_probe,
        "candidate_count": len(candidates),
        "platform_preflight": platform_report,
        "platform_inspection": platform_inspection,
        "active_requirement": active_public,
        "blockers": (
            [
                {
                    "id": "orphan_doing_without_state",
                    "detail": "task source contains doing rows without recoverable local requirement state",
                }
            ]
            if orphan_doing
            else []
        ),
        "missing_inputs": sorted(missing, key=lambda item: item["id"]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="icp-entry-v1")
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    try:
        result = preflight(Path(args.config))
    except Exception as exc:
        payload = {
            "kind": "icp.entry-preflight-failure.v1",
            "schema_version": 1,
            "status": "blocked",
            "error_type": type(exc).__name__,
            "message": "entry preflight failed",
        }
        sys.stderr.buffer.write(_canonical(payload))
        return 2
    sys.stdout.buffer.write(_canonical(result))
    return 0 if result["status"] in {"ready", "resume-required"} else 3


if __name__ == "__main__":
    raise SystemExit(main())
