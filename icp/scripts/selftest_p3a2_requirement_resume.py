#!/usr/bin/env python3
"""ICP P3a2 requirement-resume focused RED -> GREEN self-test.

Covers the two pure P3a2 modules ``requirement_claim_intent_v1.py`` and
``requirement_progress_v1.py`` and the canonical contract reference
``requirement-resume-v1.md``. Every platform remains inactive; this
self-test performs zero claim/writeback/CAS/scratch/lock and uses no
subprocess other than the import-freshness smoke check.

RED -> GREEN discipline:

1. This self-test was created BEFORE the two implementation modules.
   The first time it runs, every test that loads either module fails
   for module-absence (``FileNotFoundError``) -- that is the recorded
   RED reason.
2. After both modules are created with the approved minimum contract,
   this self-test must pass cleanly (GREEN).

Coverage matrix (table-driven where possible):

* module absence is RED before implementation;
* exact APIs, kind, schema and ordered descriptor shape for every
  document kind;
* locked identity / digest derivations and domain separation;
* forbidden command/argv/env/shell/prompt/path/task_ref/row_title/
  design_url/secret injection fails at every nesting level;
* valid claim-intent recovery: empty+before SHA -> retry-cas;
  doing+after SHA -> reconstruct-ack; all mismatch / terminal / unknown
  cases blocked;
* active pointer immutable shape and locked identity derivation;
* valid one- and multi-feature progress; sorted/unique features and
  state/replay-policy invariants;
* valid genesis and multi-receipt chain; reject reorder, duplicate id,
  gap, wrong parent, tamper, wrong requirement/progress/claim identity,
  and progress latest/count mismatch;
* resume: zero active permits new selection only with no orphan
  progress/receipts; one active takes priority; multiple active, lock
  not acquired, identity drift, progress tamper, and receipt-chain
  tamper all block;
* interruption: pending resume, checkpoint resume, started without
  receipt blocked, idempotent replay, deterministic recovery-verifier;
* missing prerequisites returns needs-user-input before any new step
  and preserves active state; blocked prerequisites block; row terminal
  requires cleanup;
* cleanup: writeback/evidence prerequisites, exact action order,
  cleanup verification, receipt-chain/evidence retention, and next
  requirement allowed only after verified cleanup;
* source AST proves stdlib-only, no filesystem/path/subprocess/network/
  write/CLI/import-time I/O, and no TaskSource/platform imports;
* the reference document contains every canonical kind, public API,
  transition, P3a2/P3d boundary, and stop rule.

Run directly:

    PYTHONDONTWRITEBYTECODE=1 \\
        python3 icp/scripts/selftest_p3a2_requirement_resume.py
"""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

ICP_ROOT = Path(__file__).resolve().parents[1]
ICP_SCRIPTS = Path(__file__).resolve().parent
CLAIM_INTENT_PATH = ICP_SCRIPTS / "requirement_claim_intent_v1.py"
PROGRESS_PATH = ICP_SCRIPTS / "requirement_progress_v1.py"
REFERENCE_PATH = ICP_ROOT / "references" / "requirement-resume-v1.md"

# Canonical kinds (the self-test independently re-states these so a
# divergence in the module is caught).
KIND_CLAIM_INTENT = "icp.requirement-claim-intent.v1"
KIND_CLAIM_RECOVERY_REPORT = "icp.claim-recovery-report.v1"
KIND_ACTIVE_REQUIREMENT = "icp.active-requirement.v1"
KIND_PROGRESS = "icp.requirement-progress.v1"
KIND_CHECKPOINT_RECEIPT = "icp.checkpoint-receipt.v1"
KIND_RESUME_DECISION = "icp.requirement-resume-decision.v1"
KIND_CLEANUP_PLAN = "icp.requirement-cleanup-plan.v1"
KIND_CLEANUP_REPORT = "icp.requirement-cleanup-report.v1"
ALL_KINDS = (
    KIND_CLAIM_INTENT, KIND_CLAIM_RECOVERY_REPORT,
    KIND_ACTIVE_REQUIREMENT, KIND_PROGRESS,
    KIND_CHECKPOINT_RECEIPT, KIND_RESUME_DECISION,
    KIND_CLEANUP_PLAN, KIND_CLEANUP_REPORT,
)
SCHEMA_VERSION = 1

CLAIM_INTENT_KEYS = (
    "kind", "schema_version", "requirement_id",
    "selection_manifest_digest", "row_identity_digest",
    "task_source_snapshot_digest", "candidate_identity_digest",
    "expected_status_before", "source_sha256_before",
    "expected_source_sha256_after",
)
RECOVERY_REPORT_KEYS = (
    "kind", "schema_version", "requirement_id", "intent_digest",
    "decision", "reason_code", "observed_status",
    "observed_source_sha256",
)
ACTIVE_KEYS = (
    "kind", "schema_version", "requirement_id",
    "selection_manifest_digest", "row_identity_digest",
    "claim_intent_digest", "claim_ack_digest", "progress_id",
)
PROGRESS_KEYS = (
    "kind", "schema_version", "requirement_id", "progress_id",
    "claim_ack_digest", "verified_operation_plan_digest",
    "revision", "phase", "latest_checkpoint_receipt_digest",
    "checkpoint_count", "feature_positions",
)
FEATURE_KEYS = (
    "feature_id", "state", "inflight_step_id", "next_step_id",
    "replay_policy", "recovery_verifier_digest",
    "last_checkpoint_receipt_digest",
)
RECEIPT_KEYS = (
    "kind", "schema_version", "receipt_id", "requirement_id",
    "progress_id", "claim_ack_digest", "sequence",
    "previous_receipt_digest", "feature_id", "step_id",
    "execution_mode", "input_artifact_digests",
    "output_artifact_digests", "producer_digest", "verifier_digest",
)
RESUME_DECISION_KEYS = (
    "kind", "schema_version", "decision", "reason_code",
    "requirement_id", "progress_id", "feature_id", "step_id",
    "checkpoint_receipt_digest",
)
CLEANUP_PLAN_KEYS = (
    "kind", "schema_version", "requirement_id", "terminal_status",
    "writeback_ack_digest", "sealed_evidence_digest", "actions",
    "next_requirement_allowed",
)
CLEANUP_REPORT_KEYS = (
    "kind", "schema_version", "requirement_id", "terminal_status",
    "cleanup_verified", "checkpoint_evidence_retained",
    "sealed_evidence_retained", "next_requirement_allowed",
)

# Fixed digest fixtures: bare 64-char lowercase SHA-256 hex. Use a mix
# of all-digit and all-letter strings to exercise the hex check.
DIGEST_SEL_MANIFEST = "a" * 64
DIGEST_ROW_IDENTITY = "b" * 64
DIGEST_TASKSOURCE_SNAPSHOT = "c" * 64
DIGEST_CANDIDATE_IDENTITY = "d" * 64
DIGEST_SHA_BEFORE = "e" * 64
DIGEST_SHA_AFTER = "f" * 64
DIGEST_CLAIM_ACK = "11" * 32          # all-digit hex
DIGEST_CLAIM_INTENT = "22" * 32
DIGEST_OP_PLAN = "33" * 32
DIGEST_SEALED_EVIDENCE = "44" * 32
DIGEST_WRITEBACK_ACK = "55" * 32
DIGEST_PRODUCER = "66" * 32
DIGEST_VERIFIER = "77" * 32
DIGEST_RECEIPT_A = "88" * 32
DIGEST_RECEIPT_B = "99" * 32
DIGEST_RECOVERY_VERIFIER = "0a" * 32  # mixed digit+letter
DIGEST_ARTIFACT = "bb" * 32

INJECTION_FIELDS = (
    "command", "argv", "shell", "interpreter", "env", "runner", "args",
    "program", "cmd", "subprocess", "exec", "run", "script_path",
    "script_runner", "activate", "activation_command",
    "activation_override", "prompt", "prompt_template", "path",
    "task_ref", "row_title", "design_url", "secret", "token",
    "password", "credential", "api_key",
)


# ---------------------------------------------------------------------------
# Module loaders and tiny helpers.
# ---------------------------------------------------------------------------


def _load(name: str, path: Path):
    if not path.exists():
        raise FileNotFoundError(f"module not found: {path}")
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise FileNotFoundError(f"cannot load spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_claim_intent():
    return _load("requirement_claim_intent_v1_selftest", CLAIM_INTENT_PATH)


def _load_progress():
    return _load("requirement_progress_v1_selftest", PROGRESS_PATH)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(payload: dict) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _expect_reject(callable_: Callable, label: str) -> None:
    try:
        callable_()
    except Exception:
        return
    raise AssertionError(f"{label}: expected rejection, got success")


def _assert_no_forbidden_keys(obj: Any, forbidden: set[str]) -> None:
    """Structured recursive key rejection. Walks dicts/lists and fails
    if any key at any nesting level is in ``forbidden``. Replaces an
    earlier false-positive substring scan that flagged legitimate
    values (e.g. the ``reconstruct-claim-ack`` decision) as leaks."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert k not in forbidden, (
                f"report carries forbidden key: {k!r}"
            )
            _assert_no_forbidden_keys(v, forbidden)
    elif isinstance(obj, list):
        for item in obj:
            _assert_no_forbidden_keys(item, forbidden)


def _reordered(src: dict, key_order: tuple) -> dict:
    """Return a copy of ``src`` with keys in reversed canonical order."""
    out: dict = {}
    for key in reversed(key_order):
        out[key] = src[key]
    return out


# ---------------------------------------------------------------------------
# Document builders (independent of the modules under test).
# ---------------------------------------------------------------------------


def _requirement_id(selection: str, row_id: str) -> str:
    return hashlib.sha256(
        b"icp.requirement.v1\x00"
        + bytes.fromhex(selection)
        + bytes.fromhex(row_id)
    ).hexdigest()


def _progress_id(requirement_id: str, claim_ack: str) -> str:
    return hashlib.sha256(
        b"icp.requirement-progress.v1\x00"
        + bytes.fromhex(requirement_id)
        + bytes.fromhex(claim_ack)
    ).hexdigest()


def _claim_intent(*, requirement_id: str | None = None) -> dict:
    if requirement_id is None:
        requirement_id = _requirement_id(
            DIGEST_SEL_MANIFEST, DIGEST_ROW_IDENTITY
        )
    return {
        "kind": KIND_CLAIM_INTENT,
        "schema_version": SCHEMA_VERSION,
        "requirement_id": requirement_id,
        "selection_manifest_digest": DIGEST_SEL_MANIFEST,
        "row_identity_digest": DIGEST_ROW_IDENTITY,
        "task_source_snapshot_digest": DIGEST_TASKSOURCE_SNAPSHOT,
        "candidate_identity_digest": DIGEST_CANDIDATE_IDENTITY,
        "expected_status_before": "empty",
        "source_sha256_before": DIGEST_SHA_BEFORE,
        "expected_source_sha256_after": DIGEST_SHA_AFTER,
    }


def _active(progress_module) -> dict:
    rid = progress_module.derive_requirement_id(
        DIGEST_SEL_MANIFEST, DIGEST_ROW_IDENTITY
    )
    pid = progress_module.derive_progress_id(rid, DIGEST_CLAIM_ACK)
    return {
        "kind": KIND_ACTIVE_REQUIREMENT,
        "schema_version": SCHEMA_VERSION,
        "requirement_id": rid,
        "selection_manifest_digest": DIGEST_SEL_MANIFEST,
        "row_identity_digest": DIGEST_ROW_IDENTITY,
        "claim_intent_digest": DIGEST_CLAIM_INTENT,
        "claim_ack_digest": DIGEST_CLAIM_ACK,
        "progress_id": pid,
    }


def _expected_identities(progress_module) -> dict:
    active = _active(progress_module)
    return {
        "requirement_id": active["requirement_id"],
        "selection_manifest_digest": DIGEST_SEL_MANIFEST,
        "row_identity_digest": DIGEST_ROW_IDENTITY,
        "claim_intent_digest": DIGEST_CLAIM_INTENT,
        "claim_ack_digest": DIGEST_CLAIM_ACK,
        "progress_id": active["progress_id"],
        "verified_operation_plan_digest": DIGEST_OP_PLAN,
    }


def _feature(
    *,
    fid: str = "artboard.login",
    state: str = "pending",
    inflight: str | None = None,
    next_step: str | None = "step.login.build",
    replay: str = "none",
    recovery_verifier: str | None = None,
    last_receipt: str | None = None,
) -> dict:
    return {
        "feature_id": fid,
        "state": state,
        "inflight_step_id": inflight,
        "next_step_id": next_step,
        "replay_policy": replay,
        "recovery_verifier_digest": recovery_verifier,
        "last_checkpoint_receipt_digest": last_receipt,
    }


def _progress(
    progress_module,
    *,
    features: list[dict] | None = None,
    phase: str = "running",
    latest: str | None = None,
    count: int | None = None,
    revision: int = 0,
) -> dict:
    if features is None:
        features = [_feature()]
    if count is None:
        count = 0 if latest is None else 1
    active = _active(progress_module)
    return {
        "kind": KIND_PROGRESS,
        "schema_version": SCHEMA_VERSION,
        "requirement_id": active["requirement_id"],
        "progress_id": active["progress_id"],
        "claim_ack_digest": DIGEST_CLAIM_ACK,
        "verified_operation_plan_digest": DIGEST_OP_PLAN,
        "revision": revision,
        "phase": phase,
        "latest_checkpoint_receipt_digest": latest,
        "checkpoint_count": count,
        "feature_positions": features,
    }


def _receipt(
    progress_module,
    *,
    sequence: int,
    receipt_id: str,
    previous_receipt_digest: str,
    feature_id: str | None = "artboard.login",
    step_id: str = "step.login.build",
) -> dict:
    active = _active(progress_module)
    return {
        "kind": KIND_CHECKPOINT_RECEIPT,
        "schema_version": SCHEMA_VERSION,
        "receipt_id": receipt_id,
        "requirement_id": active["requirement_id"],
        "progress_id": active["progress_id"],
        "claim_ack_digest": DIGEST_CLAIM_ACK,
        "sequence": sequence,
        "previous_receipt_digest": previous_receipt_digest,
        "feature_id": feature_id,
        "step_id": step_id,
        "execution_mode": "first-run",
        "input_artifact_digests": [
            {"id": "input.spec", "digest": DIGEST_ARTIFACT},
        ],
        "output_artifact_digests": [
            {"id": "output.widget", "digest": DIGEST_ARTIFACT},
        ],
        "producer_digest": DIGEST_PRODUCER,
        "verifier_digest": DIGEST_VERIFIER,
    }


def _build_chain(progress_module, n: int) -> list[dict]:
    """Build a valid chain of n receipts (n >= 0) with unique IDs."""
    assert n >= 0
    receipts: list[dict] = []
    for i in range(n):
        if i == 0:
            prev = progress_module.GENESIS_RECEIPT_DIGEST
        else:
            prev = progress_module.document_digest(receipts[i - 1])
        # Deterministic unique receipt_id per position.
        rid = hashlib.sha256(
            b"receipt.id\x00" + str(i).encode("ascii")
        ).hexdigest()
        r = _receipt(
            progress_module,
            sequence=i,
            receipt_id=rid,
            previous_receipt_digest=prev,
        )
        receipts.append(r)
    return receipts


def _resume_kwargs(
    progress_module,
    *,
    active_pointers,
    progress=None,
    receipts=None,
    expected_identities=None,
    exclusive_lock_acquired=True,
    prerequisites_status="met",
    observed_row_status="doing",
):
    if expected_identities is None:
        expected_identities = _expected_identities(progress_module)
    return dict(
        active_pointers=active_pointers,
        progress=progress,
        receipts=receipts if receipts is not None else [],
        expected_identities=expected_identities,
        exclusive_lock_acquired=exclusive_lock_acquired,
        prerequisites_status=prerequisites_status,
        observed_row_status=observed_row_status,
    )


# ---------------------------------------------------------------------------
# 1. Module presence + API surface.
# ---------------------------------------------------------------------------


def test_modules_exist_and_load() -> None:
    claim_intent = _load_claim_intent()
    progress = _load_progress()
    for name in (
        "document_digest", "verify_claim_intent",
        "verify_claim_recovery_report", "decide_claim_recovery",
    ):
        assert callable(getattr(claim_intent, name)), name
    for name in (
        "derive_requirement_id", "derive_progress_id", "document_digest",
        "verify_active_requirement", "verify_progress",
        "verify_checkpoint_receipt", "verify_checkpoint_chain",
        "decide_resume", "plan_terminal_cleanup",
        "verify_terminal_cleanup",
    ):
        assert callable(getattr(progress, name)), name


def test_claim_intent_public_api_surface_is_closed() -> None:
    import inspect
    mod = _load_claim_intent()
    expected = {
        "document_digest", "verify_claim_intent",
        "verify_claim_recovery_report", "decide_claim_recovery",
    }
    funcs = {
        n for n in dir(mod)
        if not n.startswith("_")
        and inspect.isfunction(getattr(mod, n))
        and getattr(mod, n).__module__ == mod.__name__
    }
    assert funcs == expected, f"unexpected: {sorted(funcs - expected)}"
    classes = {
        n for n in dir(mod)
        if not n.startswith("_")
        and inspect.isclass(getattr(mod, n))
        and getattr(mod, n).__module__ == mod.__name__
    }
    assert "ClaimIntentError" in classes


def test_progress_public_api_surface_is_closed() -> None:
    import inspect
    mod = _load_progress()
    expected = {
        "derive_requirement_id", "derive_progress_id", "document_digest",
        "verify_active_requirement", "verify_progress",
        "verify_checkpoint_receipt", "verify_checkpoint_chain",
        "decide_resume", "plan_terminal_cleanup",
        "verify_terminal_cleanup",
    }
    funcs = {
        n for n in dir(mod)
        if not n.startswith("_")
        and inspect.isfunction(getattr(mod, n))
        and getattr(mod, n).__module__ == mod.__name__
    }
    assert funcs == expected, f"unexpected: {sorted(funcs - expected)}"
    classes = {
        n for n in dir(mod)
        if not n.startswith("_")
        and inspect.isclass(getattr(mod, n))
        and getattr(mod, n).__module__ == mod.__name__
    }
    assert "RequirementResumeError" in classes


# ---------------------------------------------------------------------------
# 2 & 13. Source AST: stdlib only, no platform/tasksource imports, no I/O.
# ---------------------------------------------------------------------------


_ALLOWED_STDLIB = {"__future__", "hashlib", "json", "typing"}
_FORBIDDEN_IMPORT_BASES = (
    "csv_task_source", "csv_row_status_v1", "prepare_selection",
    "preflight_selection", "resolve_run_config",
    "freeze_selection_manifest", "freeze_iff_baseline",
    "verify_selection_manifest_v1", "verify_vendor_iff_v1",
    "vendor_iff_v1", "icp_common", "platform_package_contract_v1",
    "iff", "platforms", "task_sources", "design_sources", "shared_core",
)


def _imports_of(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None
            names.append(node.module)
    return names


def test_modules_use_only_stdlib() -> None:
    for path in (CLAIM_INTENT_PATH, PROGRESS_PATH):
        for name in _imports_of(path):
            top = name.split(".")[0]
            assert top in _ALLOWED_STDLIB, (
                f"{path.name}: non-stdlib import: {name}"
            )


def test_modules_do_not_import_tasksource_or_platform() -> None:
    for path in (CLAIM_INTENT_PATH, PROGRESS_PATH):
        for name in _imports_of(path):
            lowered = name.lower()
            for forb in _FORBIDDEN_IMPORT_BASES:
                assert not lowered.startswith(forb.lower()), (
                    f"{path.name} imports forbidden module: {name}"
                )


_FORBIDDEN_TOP_NAME_CALLS = {
    "open", "system", "popen", "execv", "execve", "execl",
    "spawnv", "spawnve", "fork", "urlopen",
}
_FORBIDDEN_TOP_ATTR_CALLS = {
    "open", "resolve", "stat", "lstat", "exists", "is_file", "is_dir",
    "is_symlink", "readlink", "iterdir", "glob", "rglob", "read_text",
    "read_bytes", "write_text", "write_bytes", "mkdir", "unlink",
    "replace", "rename", "touch", "chmod", "symlink_to", "hardlink_to",
}
_FORBIDDEN_TOP_ATTR_CHAINS = {
    "subprocess.run", "subprocess.call", "subprocess.check_call",
    "subprocess.check_output", "subprocess.Popen",
    "subprocess.getoutput", "subprocess.getstatusoutput",
    "os.system", "os.popen", "os.execv", "os.spawnv", "os.fork",
    "urllib.request.urlopen", "urllib.urlopen", "socket.socket",
    "fcntl.flock", "msvcrt.locking",
}


def _attr_chain(node: ast.AST) -> str:
    parts = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


def _top_level_io_violations(tree: ast.Module) -> list:
    violations = []

    def check(node: ast.Call) -> None:
        f = node.func
        if isinstance(f, ast.Name) and f.id in _FORBIDDEN_TOP_NAME_CALLS:
            violations.append(f.id)
        elif isinstance(f, ast.Attribute):
            chain = _attr_chain(f)
            last = chain.rsplit(".", 1)[-1]
            if chain in _FORBIDDEN_TOP_ATTR_CHAINS:
                violations.append(chain)
            elif last in _FORBIDDEN_TOP_ATTR_CALLS:
                violations.append(chain)

    for stmt in tree.body:
        if isinstance(
            stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            continue
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call):
                check(node)
    return violations


def test_modules_have_no_top_level_io_calls() -> None:
    for path in (CLAIM_INTENT_PATH, PROGRESS_PATH):
        tree = ast.parse(path.read_text())
        v = _top_level_io_violations(tree)
        assert v == [], f"{path.name}: top-level I/O calls: {v}"


def test_modules_import_cleanly_in_fresh_subprocess() -> None:
    code = (
        "import sys, importlib.util;"
        f"sa = importlib.util.spec_from_file_location("
        f"'a', {str(CLAIM_INTENT_PATH)!r});"
        "ma = importlib.util.module_from_spec(sa);"
        "sys.modules['a'] = ma; sa.loader.exec_module(ma);"
        f"sb = importlib.util.spec_from_file_location("
        f"'b', {str(PROGRESS_PATH)!r});"
        "mb = importlib.util.module_from_spec(sb);"
        "sys.modules['b'] = mb; sb.loader.exec_module(mb);"
        "print('IMPORT_OK');"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, (
        f"import failed: rc={result.returncode} stderr={result.stderr}"
    )
    assert result.stdout.strip() == "IMPORT_OK"


# ---------------------------------------------------------------------------
# 3. Digest / identity derivation determinism and domain separation.
# ---------------------------------------------------------------------------


def test_document_digest_matches_canonical_bytes() -> None:
    claim_intent = _load_claim_intent()
    progress = _load_progress()
    sample = {"b": 1, "a": [1, 2], "c": "x"}
    expected = _sha256_bytes(_canonical_json_bytes(sample))
    assert claim_intent.document_digest(sample) == expected
    assert progress.document_digest(sample) == expected
    # Determinism + key-order independence.
    assert claim_intent.document_digest({"a": 1, "b": 2}) == \
        claim_intent.document_digest({"b": 2, "a": 1})


def test_identity_derivation_is_domain_separated() -> None:
    progress = _load_progress()
    rid = progress.derive_requirement_id(
        DIGEST_SEL_MANIFEST, DIGEST_ROW_IDENTITY
    )
    pid = progress.derive_progress_id(rid, DIGEST_CLAIM_ACK)
    assert rid == _requirement_id(DIGEST_SEL_MANIFEST, DIGEST_ROW_IDENTITY)
    assert pid == _progress_id(rid, DIGEST_CLAIM_ACK)
    # Domain separation: a naive concatenated hash must not match.
    naive = hashlib.sha256(
        (DIGEST_SEL_MANIFEST + DIGEST_ROW_IDENTITY).encode("utf-8")
    ).hexdigest()
    assert rid != naive
    assert pid != rid
    # Mixed-case / non-hex inputs must be rejected.
    for bad in ("", "x" * 30, "A" * 64, "g" * 64, None, 1):
        _expect_reject(
            lambda b=bad: progress.derive_requirement_id(b, DIGEST_ROW_IDENTITY),
            f"derive_requirement_id bad {bad!r}",
        )
        _expect_reject(
            lambda b=bad: progress.derive_progress_id(rid, b),
            f"derive_progress_id bad {bad!r}",
        )


def test_genesis_receipt_digest_matches_locked_formula() -> None:
    progress = _load_progress()
    expected = hashlib.sha256(
        b"icp.checkpoint-receipt.v1.genesis"
    ).hexdigest()
    assert progress.GENESIS_RECEIPT_DIGEST == expected


# ---------------------------------------------------------------------------
# 4. Claim-intent shape, recovery report, and crash-window decisions.
# ---------------------------------------------------------------------------


def test_claim_intent_accepts_valid_and_rejects_shape_violations() -> None:
    mod = _load_claim_intent()
    base = _claim_intent()
    mod.verify_claim_intent(base)
    # Table-driven shape / enum / identity violations.
    bad_cases: list[tuple[str, dict]] = [
        ("reordered", _reordered(base, CLAIM_INTENT_KEYS)),
        ("unknown", {**base, "extra": "x"}),
        ("bad_kind", {**base, "kind": "icp.something.else.v1"}),
        ("bad_schema", {**base, "schema_version": 2}),
        ("bad_status", {**base, "expected_status_before": "doing"}),
        ("bad_digest", {**base, "selection_manifest_digest": "g" * 64}),
        ("upper_digest", {**base, "selection_manifest_digest": "A" * 64}),
        ("short_digest", {**base, "selection_manifest_digest": "a" * 30}),
    ]
    for label, doc in bad_cases:
        _expect_reject(
            lambda d=doc: mod.verify_claim_intent(d),
            f"claim_intent accepts {label}",
        )
    for key in CLAIM_INTENT_KEYS:
        bad = {k: v for k, v in base.items() if k != key}
        _expect_reject(
            lambda d=bad: mod.verify_claim_intent(d),
            f"claim_intent accepts missing {key}",
        )


def test_claim_intent_rejects_injection_keys_at_every_level() -> None:
    mod = _load_claim_intent()
    base = _claim_intent()
    for key in INJECTION_FIELDS:
        _expect_reject(
            lambda k=key: mod.verify_claim_intent({**base, k: "x"}),
            f"claim_intent accepts injection {key}",
        )
        nested = {**base, "nested": {key: "x"}}
        _expect_reject(
            lambda d=nested: mod.verify_claim_intent(d),
            f"claim_intent accepts nested injection {key}",
        )


def test_decide_claim_recovery_table() -> None:
    """Table-driven: status x observed-sha -> decision/reason."""
    mod = _load_claim_intent()
    intent = _claim_intent()
    common = dict(
        intent=intent,
        expected_requirement_id=intent["requirement_id"],
        expected_selection_manifest_digest=intent["selection_manifest_digest"],
        expected_row_identity_digest=intent["row_identity_digest"],
    )
    cases = [
        ("empty", DIGEST_SHA_BEFORE, "retry-cas",
         "row-empty-before-sha-match"),
        ("doing", DIGEST_SHA_AFTER, "reconstruct-claim-ack",
         "row-doing-after-sha-match"),
        ("empty", DIGEST_SHA_AFTER, "blocked", "source-sha-mismatch"),
        ("doing", DIGEST_SHA_BEFORE, "blocked", "source-sha-mismatch"),
        ("done", DIGEST_SHA_AFTER, "blocked", "unexpected-row-status"),
        ("error", DIGEST_SHA_AFTER, "blocked", "unexpected-row-status"),
        ("unknown", DIGEST_SHA_AFTER, "blocked", "unexpected-row-status"),
    ]
    for status, sha, decision, reason in cases:
        report = mod.decide_claim_recovery(
            observed_status=status, observed_source_sha256=sha, **common
        )
        assert report["decision"] == decision, (
            f"status={status} sha={sha[:4]} expected {decision} "
            f"got {report['decision']}"
        )
        assert report["reason_code"] == reason
        # Every returned report must verify.
        mod.verify_claim_recovery_report(report)
        # Report shape exact.
        assert list(report.keys()) == list(RECOVERY_REPORT_KEYS)
        assert report["intent_digest"] == mod.document_digest(intent)
        # No claim ack, row text, path, or secret in the report.
        # Use a structured recursive key walk instead of a substring
        # scan, which was a false positive (e.g. the
        # ``reconstruct-claim-ack`` decision string legitimately
        # contains the substring ``claim-ack``). The recovery report
        # schema is closed; verify the implementation never leaks an
        # ack-carrying key or any locked forbidden injection key.
        forbidden = set(INJECTION_FIELDS) | {
            "claim_ack", "claim_ack_digest", "ack", "ack_digest",
        }
        _assert_no_forbidden_keys(report, forbidden)


def test_decide_claim_recovery_rejects_invalid_intent_or_identity() -> None:
    mod = _load_claim_intent()
    intent = _claim_intent()
    base_kwargs = dict(
        intent=intent,
        expected_requirement_id=intent["requirement_id"],
        expected_selection_manifest_digest=intent["selection_manifest_digest"],
        expected_row_identity_digest=intent["row_identity_digest"],
        observed_status="empty",
        observed_source_sha256=DIGEST_SHA_BEFORE,
    )

    def vary(**over):
        kwargs = dict(base_kwargs)
        kwargs.update(over)
        return kwargs

    bad_intent = {**intent, "expected_status_before": "doing"}
    cases = [
        vary(intent=bad_intent),
        vary(expected_requirement_id="0" * 64),
        vary(expected_selection_manifest_digest="0" * 64),
        vary(expected_row_identity_digest="0" * 64),
        vary(observed_status="weird"),
        vary(observed_source_sha256="g" * 64),
        vary(observed_source_sha256="A" * 64),
    ]
    for kwargs in cases:
        _expect_reject(
            lambda k=kwargs: mod.decide_claim_recovery(**k),
            f"decide_claim_recovery accepted {kwargs}",
        )


# ---------------------------------------------------------------------------
# 5. Active-requirement pointer.
# ---------------------------------------------------------------------------


def test_active_requirement_accepts_and_derives_identities() -> None:
    progress = _load_progress()
    active = _active(progress)
    assert tuple(active.keys()) == ACTIVE_KEYS
    progress.verify_active_requirement(active)
    assert active["requirement_id"] == _requirement_id(
        DIGEST_SEL_MANIFEST, DIGEST_ROW_IDENTITY
    )
    assert active["progress_id"] == _progress_id(
        active["requirement_id"], DIGEST_CLAIM_ACK
    )


def test_active_requirement_rejects_shape_and_identity_violations() -> None:
    progress = _load_progress()
    base = _active(progress)
    bad_cases: list[tuple[str, dict]] = [
        ("reordered", _reordered(base, ACTIVE_KEYS)),
        ("unknown", {**base, "extra": "x"}),
        ("bad_kind", {**base, "kind": "icp.something.else.v1"}),
        ("bad_rid", {**base, "requirement_id": "0" * 64}),
        ("bad_pid", {**base, "progress_id": "0" * 64}),
        ("bad_digest", {**base, "selection_manifest_digest": "g" * 64}),
        ("extra_progress_digest", {**base, "progress_digest": DIGEST_ARTIFACT}),
        ("extra_phase", {**base, "phase": "running"}),
        ("extra_path", {**base, "path": "/tmp/x"}),
    ]
    for label, doc in bad_cases:
        _expect_reject(
            lambda d=doc: progress.verify_active_requirement(d),
            f"active accepts {label}",
        )
    for key in INJECTION_FIELDS:
        _expect_reject(
            lambda k=key: progress.verify_active_requirement({**base, k: "x"}),
            f"active accepts injection {key}",
        )


# ---------------------------------------------------------------------------
# 6. Requirement progress: features, sort, state/replay invariants.
# ---------------------------------------------------------------------------


def test_progress_accepts_single_and_multi_feature() -> None:
    progress = _load_progress()
    progress.verify_progress(_progress(progress))
    multi = _progress(
        progress,
        features=[
            _feature(fid="artboard.a", state="checkpointed",
                     next_step="step.next", last_receipt=DIGEST_RECEIPT_A),
            _feature(fid="artboard.b", state="started",
                     inflight="step.mid", next_step="step.mid",
                     replay="idempotent"),
            _feature(fid="artboard.c", state="pending",
                     next_step="step.first"),
        ],
    )
    progress.verify_progress(multi)


def test_progress_rejects_shape_and_feature_violations() -> None:
    progress = _load_progress()
    base = _progress(progress)
    # Top-level shape violations.
    bad_cases: list[tuple[str, dict]] = [
        ("reordered", _reordered(base, PROGRESS_KEYS)),
        ("bad_phase", {**base, "phase": "weird"}),
        ("revision_bool", {**base, "revision": True}),
        ("count_bool", {**base, "checkpoint_count": False}),
        ("count_mismatch", {
            **base,
            "latest_checkpoint_receipt_digest": None,
            "checkpoint_count": 1,
        }),
        ("empty_features", {**base, "feature_positions": []}),
    ]
    for label, doc in bad_cases:
        _expect_reject(
            lambda d=doc: progress.verify_progress(d),
            f"progress accepts {label}",
        )
    # Feature-level violations.
    feature_bad: list[tuple[str, list[dict]]] = [
        ("unsorted", [
            _feature(fid="artboard.b"),
            _feature(fid="artboard.a"),
        ]),
        ("duplicate", [
            _feature(fid="artboard.a"),
            _feature(fid="artboard.a"),
        ]),
        ("started_no_inflight", [
            _feature(state="started", inflight=None),
        ]),
        ("deterministic_no_verifier", [
            _feature(state="started", inflight="step.mid",
                     replay="deterministic-recovery",
                     recovery_verifier=None),
        ]),
        ("idempotent_with_verifier", [
            _feature(state="started", inflight="step.mid",
                     replay="idempotent",
                     recovery_verifier=DIGEST_RECOVERY_VERIFIER),
        ]),
        ("bad_safe_id", [_feature(fid="Bad ID With Space")]),
        ("long_safe_id", [_feature(fid="a" * 129)]),
    ]
    for label, feats in feature_bad:
        doc = _progress(progress, features=feats)
        _expect_reject(
            lambda d=doc: progress.verify_progress(d),
            f"progress feature_positions accepts {label}",
        )
    for key in INJECTION_FIELDS:
        feat = {**_feature(), key: "x"}
        doc = _progress(progress, features=[feat])
        _expect_reject(
            lambda d=doc: progress.verify_progress(d),
            f"progress feature_positions accepts injection {key}",
        )


# ---------------------------------------------------------------------------
# 7. Checkpoint receipt + chain (table-driven).
# ---------------------------------------------------------------------------


def test_checkpoint_receipt_accepts_valid_and_rejects_violations() -> None:
    progress = _load_progress()
    rec = _receipt(
        progress, sequence=0, receipt_id=DIGEST_RECEIPT_A,
        previous_receipt_digest=progress.GENESIS_RECEIPT_DIGEST,
    )
    progress.verify_checkpoint_receipt(rec)
    # Tamper table.
    bad_cases: list[tuple[str, dict]] = [
        ("reordered", _reordered(rec, RECEIPT_KEYS)),
        ("bad_kind", {**rec, "kind": "icp.something.else.v1"}),
        ("bad_digest", {**rec, "receipt_id": "g" * 64}),
        ("upper_digest", {**rec, "producer_digest": "A" * 64}),
        ("sequence_bool", {**rec, "sequence": True}),
        ("bad_step_id", {**rec, "step_id": "Bad Step"}),
        ("bad_exec_mode", {**rec, "execution_mode": "frob"}),
        ("bad_artifact_id", {
            **rec,
            "input_artifact_digests": [
                {"id": "Bad ID", "digest": DIGEST_ARTIFACT},
            ],
        }),
        ("unsorted_artifacts", {
            **rec,
            "output_artifact_digests": [
                {"id": "z.id", "digest": DIGEST_ARTIFACT},
                {"id": "a.id", "digest": DIGEST_ARTIFACT},
            ],
        }),
    ]
    for label, doc in bad_cases:
        _expect_reject(
            lambda d=doc: progress.verify_checkpoint_receipt(d),
            f"receipt accepts {label}",
        )
    for key in INJECTION_FIELDS:
        bad = {**rec, key: "x"}
        _expect_reject(
            lambda d=bad: progress.verify_checkpoint_receipt(d),
            f"receipt accepts injection {key}",
        )
        nested = copy.deepcopy(rec)
        nested["input_artifact_digests"][0][key] = "x"
        _expect_reject(
            lambda d=nested: progress.verify_checkpoint_receipt(d),
            f"receipt artifact accepts injection {key}",
        )


def test_checkpoint_chain_accepts_genesis_and_multi_receipt() -> None:
    progress = _load_progress()
    active = _active(progress)
    # Genesis-only chain.
    r0 = _build_chain(progress, 1)[0]
    prog = _progress(
        progress,
        features=[_feature(state="checkpointed", next_step="step.next",
                           last_receipt=progress.document_digest(r0))],
        latest=progress.document_digest(r0), count=1,
    )
    progress.verify_checkpoint_chain([r0], active=active, progress=prog)
    # Multi-receipt chain.
    chain = _build_chain(progress, 3)
    prog3 = _progress(
        progress,
        features=[_feature(state="checkpointed", next_step="step.next",
                           last_receipt=progress.document_digest(chain[-1]))],
        latest=progress.document_digest(chain[-1]), count=3,
    )
    progress.verify_checkpoint_chain(
        chain, active=active, progress=prog3
    )


def test_checkpoint_chain_rejects_tamper_table() -> None:
    progress = _load_progress()
    active = _active(progress)
    r0, r1 = _build_chain(progress, 2)
    prog2 = _progress(
        progress,
        features=[_feature(state="checkpointed", next_step="step.next",
                           last_receipt=progress.document_digest(r1))],
        latest=progress.document_digest(r1), count=2,
    )

    def run_with(chain, prog=prog2):
        return progress.verify_checkpoint_chain(
            chain, active=active, progress=prog
        )

    # 1) Reorder.
    _expect_reject(lambda: run_with([r1, r0]), "chain accepts reorder")
    # 2) Duplicate receipt_id. Make ``dup`` truly share ``r0``'s id
    #    while keeping every other chain invariant valid (sequence=1,
    #    parent=r0's digest, identity fields still match ``active``)
    #    so the rejection fires from the unique-receipt_id rule alone.
    dup = copy.deepcopy(r1)
    dup["receipt_id"] = r0["receipt_id"]
    _expect_reject(lambda: run_with([r0, dup]), "chain accepts dup id")
    # 3) Gap.
    r_gap = copy.deepcopy(r1)
    r_gap["sequence"] = 2
    r_gap["previous_receipt_digest"] = progress.document_digest(r0)
    _expect_reject(lambda: run_with([r0, r_gap]), "chain accepts gap")
    # 4) Wrong parent link.
    r_wrong = copy.deepcopy(r1)
    r_wrong["previous_receipt_digest"] = DIGEST_RECEIPT_A
    _expect_reject(lambda: run_with([r0, r_wrong]), "chain accepts wrong parent")
    # 5) Tampered receipt body.
    r_tamper = copy.deepcopy(r1)
    r_tamper["step_id"] = "step.tampered"
    _expect_reject(
        lambda: run_with([r0, r_tamper]),
        "chain accepts tampered receipt",
    )
    # 6) Wrong requirement_id in receipt.
    r_rid = copy.deepcopy(r1)
    r_rid["requirement_id"] = "0" * 64
    _expect_reject(
        lambda: run_with([r0, r_rid]),
        "chain accepts wrong requirement_id",
    )
    # 7) Wrong progress_id in receipt.
    r_pid = copy.deepcopy(r1)
    r_pid["progress_id"] = "0" * 64
    _expect_reject(
        lambda: run_with([r0, r_pid]),
        "chain accepts wrong progress_id",
    )
    # 8) Wrong claim_ack_digest in receipt.
    r_ack = copy.deepcopy(r1)
    r_ack["claim_ack_digest"] = "0" * 64
    _expect_reject(
        lambda: run_with([r0, r_ack]),
        "chain accepts wrong claim_ack_digest",
    )
    # 9) Genesis with non-genesis parent.
    bad_gen = copy.deepcopy(r0)
    bad_gen["previous_receipt_digest"] = DIGEST_RECEIPT_A
    prog1 = _progress(
        progress,
        features=[_feature(state="checkpointed",
                           last_receipt=progress.document_digest(bad_gen))],
        latest=progress.document_digest(bad_gen), count=1,
    )
    _expect_reject(
        lambda: progress.verify_checkpoint_chain(
            [bad_gen], active=active, progress=prog1
        ),
        "chain accepts non-genesis parent at sequence 0",
    )
    # 10) Latest digest mismatch.
    bad_latest = copy.deepcopy(prog2)
    bad_latest["latest_checkpoint_receipt_digest"] = DIGEST_RECEIPT_A
    _expect_reject(
        lambda: run_with([r0, r1], prog=bad_latest),
        "chain accepts latest digest mismatch",
    )
    # 11) Count mismatch.
    bad_count = copy.deepcopy(prog2)
    bad_count["checkpoint_count"] = 1
    _expect_reject(
        lambda: run_with([r0, r1], prog=bad_count),
        "chain accepts count mismatch",
    )


# ---------------------------------------------------------------------------
# 8. Resume decision table.
# ---------------------------------------------------------------------------


def test_decide_resume_new_selection_only_with_zero_active_and_no_orphans() -> None:
    progress = _load_progress()
    # Zero active, no orphans -> new selection.
    decision = progress.decide_resume(
        **_resume_kwargs(progress, active_pointers=[], progress=None)
    )
    assert decision["decision"] == "new-selection-allowed"
    assert decision["reason_code"] == "no-active-state"
    assert decision["requirement_id"] is None
    assert decision["progress_id"] is None
    assert tuple(decision.keys()) == RESUME_DECISION_KEYS
    # Zero active + orphan progress -> blocked.
    orphan_prog = _progress(progress)
    decision2 = progress.decide_resume(
        **_resume_kwargs(
            progress, active_pointers=[], progress=orphan_prog,
        )
    )
    assert decision2["decision"] == "blocked"
    # Zero active + orphan receipts -> blocked.
    chain = _build_chain(progress, 1)
    decision3 = progress.decide_resume(
        **_resume_kwargs(
            progress, active_pointers=[], progress=None, receipts=chain,
        )
    )
    assert decision3["decision"] == "blocked"


def test_decide_resume_blocks_table() -> None:
    """Table-driven: various blocked/needs-user-input scenarios."""
    progress = _load_progress()
    active = _active(progress)
    identities = _expected_identities(progress)
    prog_running = _progress(
        progress,
        features=[_feature(state="pending", next_step="step.next")],
    )

    # Multiple active pointers.
    d = progress.decide_resume(**_resume_kwargs(
        progress, active_pointers=[active, active], progress=prog_running,
    ))
    assert (d["decision"], d["reason_code"]) == (
        "blocked", "multiple-active-pointers",
    )

    # Lock not acquired.
    d = progress.decide_resume(**_resume_kwargs(
        progress, active_pointers=[active], progress=prog_running,
        exclusive_lock_acquired=False,
    ))
    assert (d["decision"], d["reason_code"]) == (
        "blocked", "lock-not-acquired",
    )

    # Active identity drift.
    drift = dict(identities, requirement_id="0" * 64)
    d = progress.decide_resume(**_resume_kwargs(
        progress, active_pointers=[active], progress=prog_running,
        expected_identities=drift,
    ))
    assert (d["decision"], d["reason_code"]) == (
        "blocked", "identity-mismatch",
    )

    # Active shape tamper.
    bad_active = dict(active, progress_id="0" * 64)
    d = progress.decide_resume(**_resume_kwargs(
        progress, active_pointers=[bad_active], progress=prog_running,
    ))
    assert d["decision"] == "blocked"
    assert d["reason_code"] in ("progress-tamper", "identity-mismatch")

    # Progress missing.
    d = progress.decide_resume(**_resume_kwargs(
        progress, active_pointers=[active], progress=None,
    ))
    assert (d["decision"], d["reason_code"]) == (
        "blocked", "progress-missing",
    )

    # Progress tamper (bad phase).
    bad_prog = dict(prog_running, phase="weird")
    d = progress.decide_resume(**_resume_kwargs(
        progress, active_pointers=[active], progress=bad_prog,
    ))
    assert (d["decision"], d["reason_code"]) == (
        "blocked", "progress-tamper",
    )

    # Receipt-chain tamper (count mismatch).
    d = progress.decide_resume(**_resume_kwargs(
        progress, active_pointers=[active], progress=prog_running,
        receipts=_build_chain(progress, 1),
    ))
    assert (d["decision"], d["reason_code"]) == (
        "blocked", "receipt-chain-tamper",
    )

    # Row terminal (done) with running phase -> row-terminal.
    d = progress.decide_resume(**_resume_kwargs(
        progress, active_pointers=[active], progress=prog_running,
        observed_row_status="done",
    ))
    assert (d["decision"], d["reason_code"]) == (
        "terminal-cleanup-required", "row-terminal",
    )
    # Row empty / unknown -> row-not-doing.
    d = progress.decide_resume(**_resume_kwargs(
        progress, active_pointers=[active], progress=prog_running,
        observed_row_status="empty",
    ))
    assert (d["decision"], d["reason_code"]) == (
        "blocked", "row-not-doing",
    )

    # Prereq missing -> needs-user-input (preserve active).
    d = progress.decide_resume(**_resume_kwargs(
        progress, active_pointers=[active], progress=prog_running,
        prerequisites_status="missing",
    ))
    assert (d["decision"], d["reason_code"]) == (
        "needs-user-input", "prerequisites-missing",
    )
    assert d["requirement_id"] == active["requirement_id"]

    # Prereq blocked -> blocked.
    d = progress.decide_resume(**_resume_kwargs(
        progress, active_pointers=[active], progress=prog_running,
        prerequisites_status="blocked",
    ))
    assert (d["decision"], d["reason_code"]) == (
        "blocked", "prerequisites-blocked",
    )

    # Terminal-pending phase -> cleanup.
    prog_terminal = _progress(
        progress, phase="terminal-pending",
        features=[_feature(state="done", next_step=None)],
    )
    d = progress.decide_resume(**_resume_kwargs(
        progress, active_pointers=[active], progress=prog_terminal,
    ))
    assert (d["decision"], d["reason_code"]) == (
        "terminal-cleanup-required", "terminal-pending",
    )


def test_decide_resume_feature_step_table() -> None:
    """Table-driven: feature state x replay policy -> step decision."""
    progress = _load_progress()
    active = _active(progress)

    cases: list[tuple[str, dict, str, str, str | None]] = [
        # (label, feature, expected_decision, expected_reason, expected_step)
        ("started_no_replay",
         _feature(state="started", inflight="step.mid",
                  next_step="step.mid", replay="none"),
         "blocked", "started-without-replay", "step.mid"),
        ("started_idempotent",
         _feature(state="started", inflight="step.mid",
                  next_step="step.mid", replay="idempotent"),
         "replay-step", "replay-idempotent", "step.mid"),
        ("started_deterministic",
         _feature(state="started", inflight="step.mid",
                  next_step="step.mid", replay="deterministic-recovery",
                  recovery_verifier=DIGEST_RECOVERY_VERIFIER),
         "run-recovery-verifier", "recovery-verifier-required",
         "step.mid"),
        ("pending",
         _feature(state="pending", next_step="step.first"),
         "resume-step", "resume-next-step", "step.first"),
        ("checkpointed",
         _feature(state="checkpointed", next_step="step.green",
                  last_receipt=DIGEST_RECEIPT_A),
         "resume-step", "resume-next-step", "step.green"),
        ("failed",
         _feature(state="failed", next_step=None),
         "blocked", "active-present", None),
    ]
    for label, feat, expected_decision, expected_reason, expected_step in cases:
        prog = _progress(progress, features=[feat])
        receipts: list[dict] = []
        # If the feature has a last_checkpoint_receipt_digest, also
        # build a real 1-receipt chain and pin count/latest and the
        # feature's last-receipt to that chain's actual digest so
        # ``verify_checkpoint_chain`` is consistent (and does not
        # short-circuit decide_resume at the receipt-chain step).
        if feat["last_checkpoint_receipt_digest"] is not None:
            chain = _build_chain(progress, 1)
            real_digest = progress.document_digest(chain[-1])
            feat = dict(feat)
            feat["last_checkpoint_receipt_digest"] = real_digest
            prog = _progress(
                progress, features=[feat],
                latest=real_digest, count=1,
            )
            receipts = chain
        d = progress.decide_resume(**_resume_kwargs(
            progress, active_pointers=[active], progress=prog,
            receipts=receipts,
        ))
        assert d["decision"] == expected_decision, (
            f"{label}: expected {expected_decision} got {d['decision']}"
        )
        assert d["reason_code"] == expected_reason, (
            f"{label}: expected {expected_reason} got {d['reason_code']}"
        )
        if expected_step is not None:
            assert d["step_id"] == expected_step, (
                f"{label}: expected step {expected_step} got {d['step_id']}"
            )
        assert d["requirement_id"] == active["requirement_id"]
        assert d["progress_id"] == active["progress_id"]


def test_decide_resume_rejects_bad_inputs() -> None:
    progress = _load_progress()
    identities = _expected_identities(progress)
    for kwargs in (
        dict(active_pointers="not a list", progress=None, receipts=[],
             expected_identities=identities,
             exclusive_lock_acquired=True,
             prerequisites_status="met", observed_row_status="doing"),
        dict(active_pointers=[], progress=None, receipts=[],
             expected_identities=identities,
             exclusive_lock_acquired=True,
             prerequisites_status="weird", observed_row_status="doing"),
        dict(active_pointers=[], progress=None, receipts=[],
             expected_identities=identities,
             exclusive_lock_acquired=True,
             prerequisites_status="met", observed_row_status="weird"),
        dict(active_pointers=[], progress=None, receipts=[],
             expected_identities={},
             exclusive_lock_acquired=True,
             prerequisites_status="met", observed_row_status="doing"),
    ):
        _expect_reject(
            lambda k=kwargs: progress.decide_resume(**k),
            f"decide_resume accepted bad input",
        )


# ---------------------------------------------------------------------------
# 9. Terminal cleanup: plan + verify.
# ---------------------------------------------------------------------------


def test_plan_terminal_cleanup_accepts_valid_and_rejects_violations() -> None:
    progress = _load_progress()
    active = _active(progress)
    prog_terminal = _progress(
        progress, phase="terminal-pending",
        features=[_feature(state="done", next_step=None)],
    )
    plan = progress.plan_terminal_cleanup(
        active, prog_terminal,
        terminal_status="done",
        writeback_ack_digest=DIGEST_WRITEBACK_ACK,
        expected_writeback_ack_digest=DIGEST_WRITEBACK_ACK,
        sealed_evidence_digest=DIGEST_SEALED_EVIDENCE,
    )
    assert tuple(plan.keys()) == CLEANUP_PLAN_KEYS
    assert plan["kind"] == KIND_CLEANUP_PLAN
    assert plan["actions"] == [
        "remove-active-pointer", "remove-progress",
        "remove-scratch", "verify-cleanup",
    ]
    assert plan["next_requirement_allowed"] is False
    # Reject table.
    prog_running = _progress(
        progress, phase="running",
        features=[_feature(state="pending", next_step="step.x")],
    )
    bad_cases = [
        ("wrong_phase", dict(
            active=active, progress=prog_running,
            terminal_status="done",
            writeback_ack_digest=DIGEST_WRITEBACK_ACK,
            expected_writeback_ack_digest=DIGEST_WRITEBACK_ACK,
            sealed_evidence_digest=DIGEST_SEALED_EVIDENCE,
        )),
        ("bad_terminal_status", dict(
            active=active, progress=prog_terminal,
            terminal_status="running",
            writeback_ack_digest=DIGEST_WRITEBACK_ACK,
            expected_writeback_ack_digest=DIGEST_WRITEBACK_ACK,
            sealed_evidence_digest=DIGEST_SEALED_EVIDENCE,
        )),
        ("writeback_mismatch", dict(
            active=active, progress=prog_terminal,
            terminal_status="done",
            writeback_ack_digest=DIGEST_WRITEBACK_ACK,
            expected_writeback_ack_digest=DIGEST_SEALED_EVIDENCE,
            sealed_evidence_digest=DIGEST_SEALED_EVIDENCE,
        )),
        ("missing_sealed_evidence", dict(
            active=active, progress=prog_terminal,
            terminal_status="done",
            writeback_ack_digest=DIGEST_WRITEBACK_ACK,
            expected_writeback_ack_digest=DIGEST_WRITEBACK_ACK,
            sealed_evidence_digest=None,
        )),
        ("malformed_sealed_evidence", dict(
            active=active, progress=prog_terminal,
            terminal_status="done",
            writeback_ack_digest=DIGEST_WRITEBACK_ACK,
            expected_writeback_ack_digest=DIGEST_WRITEBACK_ACK,
            sealed_evidence_digest="x" * 30,
        )),
    ]
    for label, kwargs in bad_cases:
        _expect_reject(
            lambda k=kwargs: progress.plan_terminal_cleanup(**k),
            f"plan_terminal_cleanup accepted {label}",
        )


def test_verify_terminal_cleanup_table() -> None:
    progress = _load_progress()
    active = _active(progress)
    prog_terminal = _progress(
        progress, phase="terminal-pending",
        features=[_feature(state="done", next_step=None)],
    )
    plan = progress.plan_terminal_cleanup(
        active, prog_terminal,
        terminal_status="done",
        writeback_ack_digest=DIGEST_WRITEBACK_ACK,
        expected_writeback_ack_digest=DIGEST_WRITEBACK_ACK,
        sealed_evidence_digest=DIGEST_SEALED_EVIDENCE,
    )
    # Success path.
    report = progress.verify_terminal_cleanup(
        plan,
        active_present=False,
        progress_present=False,
        scratch_present=False,
        checkpoint_chain_digest_before=DIGEST_RECEIPT_A,
        checkpoint_chain_digest_after=DIGEST_RECEIPT_A,
        sealed_evidence_digest_after=plan["sealed_evidence_digest"],
    )
    assert tuple(report.keys()) == CLEANUP_REPORT_KEYS
    assert report["cleanup_verified"] is True
    assert report["checkpoint_evidence_retained"] is True
    assert report["sealed_evidence_retained"] is True
    assert report["next_requirement_allowed"] is True
    # Fail-closed table.
    base = dict(
        active_present=False, progress_present=False, scratch_present=False,
        checkpoint_chain_digest_before=DIGEST_RECEIPT_A,
        checkpoint_chain_digest_after=DIGEST_RECEIPT_A,
        sealed_evidence_digest_after=plan["sealed_evidence_digest"],
    )

    def vary(**over):
        kwargs = dict(base)
        kwargs.update(over)
        return kwargs

    for label, kwargs in (
        ("active_still_present", vary(active_present=True)),
        ("progress_still_present", vary(progress_present=True)),
        ("scratch_still_present", vary(scratch_present=True)),
        ("chain_drift", vary(checkpoint_chain_digest_after=DIGEST_RECEIPT_B)),
        ("evidence_drift", vary(sealed_evidence_digest_after=DIGEST_ARTIFACT)),
        ("evidence_missing", vary(sealed_evidence_digest_after=None)),
    ):
        _expect_reject(
            lambda k=kwargs: progress.verify_terminal_cleanup(plan, **k),
            f"verify_terminal_cleanup accepted {label}",
        )


# ---------------------------------------------------------------------------
# 10. Reference document coverage.
# ---------------------------------------------------------------------------


def test_reference_document_exists_and_contains_every_canonical_kind() -> None:
    assert REFERENCE_PATH.exists()
    text = REFERENCE_PATH.read_text()
    for kind in ALL_KINDS:
        assert kind in text, f"reference missing kind {kind}"


def test_reference_document_contains_every_public_api() -> None:
    text = REFERENCE_PATH.read_text()
    for api in (
        "document_digest", "verify_claim_intent",
        "verify_claim_recovery_report", "decide_claim_recovery",
        "derive_requirement_id", "derive_progress_id",
        "verify_active_requirement", "verify_progress",
        "verify_checkpoint_receipt", "verify_checkpoint_chain",
        "decide_resume", "plan_terminal_cleanup",
        "verify_terminal_cleanup",
    ):
        assert api in text, f"reference missing API {api}"


def test_reference_document_contains_transitions_boundary_and_stop_rules() -> None:
    text = REFERENCE_PATH.read_text()
    for token in (
        "P3a2", "P3d", "domain-separated", "GENESIS_RECEIPT_DIGEST",
        "new-selection-allowed", "terminal-cleanup-required",
        "needs-user-input", "source-sha-mismatch",
        "intent-identity-mismatch", "started-without-replay",
        "recovery-verifier-required", "prerequisites-missing",
        "multiple-active-pointers", "lock-not-acquired",
        "receipt-chain-tamper", "progress-tamper", "row-terminal",
        "resume-next-step", "replay-idempotent",
        "Stop rules", "stop", "boundary", "canonical",
    ):
        assert token in text, f"reference missing token {token!r}"


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
