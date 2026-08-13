# ICP P3a2 Requirement Resume v1 Contract

Status: pure contract only; every platform remains inactive; production
publication, locking, CAS, scratch cleanup, and real receipt persistence
are deferred to P3d. This reference is the canonical requirement-resume
contract authored for P3a2; it is not a byte copy of any external file.

## 1. Scope

P3a2 freezes only the data layer:

- the canonical schema and fail-closed verifiers for every
  requirement-resume document kind;
- the locked SHA-256 derivations of `requirement_id`, `progress_id`,
  document digests, and the genesis receipt digest;
- the pure crash-window recovery, resume, and terminal-cleanup decision
  state machines.

P3a2 performs:

- zero filesystem I/O, locking, CAS, subprocess, network, or writes;
- zero production claim, writeback, receipt persistence, scratch
  creation, or unlink/cleanup;
- zero TaskSource, platform-package, vendor, or registry imports.

P3a2 is task-source-neutral: nothing in this contract names CSV,
`csv_task_source`, `csv_row_status_v1`, `prepare_selection`, platform
modules, or production publishers.

## 2. Canonical kinds (alphabetical)

| Kind | Owner module |
|---|---|
| `icp.active-requirement.v1` | `icp/scripts/requirement_progress_v1.py` |
| `icp.checkpoint-receipt.v1` | `icp/scripts/requirement_progress_v1.py` |
| `icp.claim-recovery-report.v1` | `icp/scripts/requirement_claim_intent_v1.py` |
| `icp.requirement-claim-intent.v1` | `icp/scripts/requirement_claim_intent_v1.py` |
| `icp.requirement-cleanup-plan.v1` | `icp/scripts/requirement_progress_v1.py` |
| `icp.requirement-cleanup-report.v1` | `icp/scripts/requirement_progress_v1.py` |
| `icp.requirement-progress.v1` | `icp/scripts/requirement_progress_v1.py` |
| `icp.requirement-resume-decision.v1` | `icp/scripts/requirement_progress_v1.py` |

## 3. Public API

### 3.1 Module `icp/scripts/requirement_claim_intent_v1.py`

```
document_digest(document: dict) -> str
verify_claim_intent(document: dict) -> None
verify_claim_recovery_report(document: dict) -> None
decide_claim_recovery(
    intent: dict,
    *,
    expected_requirement_id: str,
    expected_selection_manifest_digest: str,
    expected_row_identity_digest: str,
    observed_status: str,
    observed_source_sha256: str,
) -> dict
```

Local error class: `ClaimIntentError(ValueError)`.

### 3.2 Module `icp/scripts/requirement_progress_v1.py`

```
derive_requirement_id(selection_manifest_digest: str, row_identity_digest: str) -> str
derive_progress_id(requirement_id: str, claim_ack_digest: str) -> str
document_digest(document: dict) -> str
verify_active_requirement(document: dict) -> None
verify_progress(document: dict) -> None
verify_checkpoint_receipt(document: dict) -> None
verify_checkpoint_chain(receipts: list[dict], *, active: dict, progress: dict) -> None
decide_resume(
    active_pointers: list[dict],
    *,
    progress: dict | None,
    receipts: list[dict],
    expected_identities: dict,
    exclusive_lock_acquired: bool,
    prerequisites_status: str,
    observed_row_status: str,
) -> dict
plan_terminal_cleanup(
    active: dict,
    progress: dict,
    *,
    terminal_status: str,
    writeback_ack_digest: str,
    expected_writeback_ack_digest: str,
    sealed_evidence_digest: str | None,
) -> dict
verify_terminal_cleanup(
    cleanup_plan: dict,
    *,
    active_present: bool,
    progress_present: bool,
    scratch_present: bool,
    checkpoint_chain_digest_before: str,
    checkpoint_chain_digest_after: str,
    sealed_evidence_digest_after: str | None,
) -> dict
```

Local error class: `RequirementResumeError(ValueError)`.

Both modules use only the Python standard library (`hashlib`, `json`,
`typing`). They expose no CLI, perform no import-time I/O, and never
inspect a filesystem or acquire a lock; `exclusive_lock_acquired` is a
verified P3d input.

## 4. Canonical bytes and digest derivations

Canonical bytes for every document:

```python
(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
```

`document_digest(document) = sha256(canonical_bytes(document))`. Documents
contain no self-referential digest field.

```
requirement_id = sha256(b"icp.requirement.v1\x00"
                        + bytes.fromhex(selection_manifest_digest)
                        + bytes.fromhex(row_identity_digest)).hexdigest()

progress_id    = sha256(b"icp.requirement-progress.v1\x00"
                        + bytes.fromhex(requirement_id)
                        + bytes.fromhex(claim_ack_digest)).hexdigest()

GENESIS_RECEIPT_DIGEST = sha256(b"icp.checkpoint-receipt.v1.genesis").hexdigest()
```

The two identity derivations are domain-separated digests: each formula
prefixes its input with a distinct ASCII domain tag and the binary
concatenation of the parent identities, so a `requirement_id` and a
`progress_id` can never collide and neither can be re-derived from a
non-domain-separated hash. Every identity and digest field is a bare
64-character lowercase SHA-256 hex string.

## 5. Document schemas

For every kind, keys must appear in the exact order listed, with the
exact type / enum / nullness described. Unknown keys, missing keys,
duplicate-at-source-builder keys, reordered keys, malformed values, and
forbidden injection keys (see section 9) fail closed at every nesting
level.

### 5.1 `icp.requirement-claim-intent.v1`

```
kind = "icp.requirement-claim-intent.v1"
schema_version = 1
requirement_id                              # sha256
selection_manifest_digest                   # sha256
row_identity_digest                         # sha256
task_source_snapshot_digest                 # sha256
candidate_identity_digest                   # sha256
expected_status_before = "empty"            # fixed enum of one
source_sha256_before                        # sha256
expected_source_sha256_after                # sha256
```

All seven identity/digest fields are bare 64-char lowercase SHA-256 hex.
`expected_status_before` is fixed to `"empty"`. No nulls, no free text,
no path/command/env/argv/shell/prompt, no row contents, no task
reference.

### 5.2 `icp.claim-recovery-report.v1`

```
kind = "icp.claim-recovery-report.v1"
schema_version = 1
requirement_id                              # sha256
intent_digest                               # sha256 (digest of the intent document)
decision       = "retry-cas" | "reconstruct-claim-ack" | "blocked"
reason_code    = "row-empty-before-sha-match" | "row-doing-after-sha-match"
               | "intent-identity-mismatch" | "source-sha-mismatch"
               | "unexpected-row-status"
observed_status    = "empty" | "doing" | "done" | "error" | "unknown"
observed_source_sha256                     # sha256
```

No report contains claim-ack fields, row title, task reference, path,
source contents, or secret. Every returned report passes
`verify_claim_recovery_report` before return.

### 5.3 `icp.active-requirement.v1`

```
kind = "icp.active-requirement.v1"
schema_version = 1
requirement_id                              # sha256, locked derivation
selection_manifest_digest                   # sha256
row_identity_digest                         # sha256
claim_intent_digest                         # sha256 (digest of the intent document)
claim_ack_digest                            # sha256
progress_id                                 # sha256, locked derivation
```

The active pointer is immutable and created only after a claim ack is
verified or reconstructed. It binds a stable `progress_id`; it never
stores the changing progress-document digest, a mutable lifecycle flag,
a path, or any task content. Verification re-derives `requirement_id`
and `progress_id` from the locked formulas and requires equality.

### 5.4 `icp.requirement-progress.v1`

```
kind = "icp.requirement-progress.v1"
schema_version = 1
requirement_id                              # sha256
progress_id                                 # sha256
claim_ack_digest                            # sha256
verified_operation_plan_digest              # sha256
revision                                    # non-negative integer (booleans rejected)
phase = "claimed" | "running" | "terminal-pending"
latest_checkpoint_receipt_digest            # sha256 | null
checkpoint_count                            # non-negative integer (booleans rejected)
feature_positions[]                         # non-empty, strictly sorted by unique feature_id
```

`checkpoint_count = 0` iff `latest_checkpoint_receipt_digest` is null.
Each feature position has the exact ordered keys:

```
feature_id
state = "pending" | "started" | "checkpointed" | "done" | "failed"
inflight_step_id          = safe-id | null
next_step_id              = safe-id | null
replay_policy             = "none" | "idempotent" | "deterministic-recovery"
recovery_verifier_digest  = sha256 | null
last_checkpoint_receipt_digest = sha256 | null
```

Rules: `started` requires `inflight_step_id`; `deterministic-recovery`
requires `recovery_verifier_digest`; the other replay policies require
it null. Safe IDs contain only lowercase ASCII letters, digits, `.`,
`_`, `-`, are non-empty, and have length <=128. Progress stores no row
text and no path.

### 5.5 `icp.checkpoint-receipt.v1`

```
kind = "icp.checkpoint-receipt.v1"
schema_version = 1
receipt_id                                 # sha256 (opaque, unique within the chain)
requirement_id                             # sha256
progress_id                                # sha256
claim_ack_digest                           # sha256
sequence                                   # non-negative integer (booleans rejected)
previous_receipt_digest                    # sha256 (genesis for sequence 0)
feature_id                                 # safe-id | null
step_id                                    # safe-id (required, non-null)
execution_mode = "first-run" | "idempotent-replay" | "deterministic-recovery"
input_artifact_digests[]                   # list of {id, digest}
output_artifact_digests[]                  # list of {id, digest}
producer_digest                            # sha256
verifier_digest                            # sha256
```

Each artifact digest pair has the exact ordered keys `id` then `digest`.
Both artifact lists are strictly sorted by unique safe `id`; all
digests are bare 64-char lowercase SHA-256 hex.

Chain verification (`verify_checkpoint_chain`) requires:

- `active` and `progress` each pass their verifier;
- `active` / `progress` `requirement_id`, `progress_id`, and
  `claim_ack_digest` agree;
- `progress.checkpoint_count == len(receipts)`;
- every receipt passes `verify_checkpoint_receipt` and binds to the
  same `requirement_id`, `progress_id`, `claim_ack_digest`;
- `receipt_id` values are unique;
- `sequence` starts at 0 and is contiguous in input order (rejects
  reorder, gap, duplicate sequence);
- `receipts[0].previous_receipt_digest == GENESIS_RECEIPT_DIGEST`,
  and for `i > 0`, `receipts[i].previous_receipt_digest ==
  document_digest(receipts[i-1])`;
- when `len(receipts) == 0`,
  `progress.latest_checkpoint_receipt_digest` is null; otherwise it
  equals `document_digest(receipts[-1])`.

### 5.6 `icp.requirement-resume-decision.v1`

```
kind = "icp.requirement-resume-decision.v1"
schema_version = 1
decision = "new-selection-allowed" | "resume-step" | "replay-step"
          | "run-recovery-verifier" | "needs-user-input"
          | "terminal-cleanup-required" | "blocked"
reason_code = "no-active-state" | "active-present"
            | "multiple-active-pointers" | "lock-not-acquired"
            | "prerequisites-missing" | "prerequisites-blocked"
            | "identity-mismatch" | "progress-missing" | "progress-tamper"
            | "receipt-chain-tamper" | "row-not-doing" | "row-terminal"
            | "started-without-replay" | "resume-next-step"
            | "replay-idempotent" | "recovery-verifier-required"
            | "terminal-pending"
requirement_id              # sha256 | null
progress_id                 # sha256 | null
feature_id                  # safe-id | null
step_id                     # safe-id | null
checkpoint_receipt_digest   # sha256 | null
```

`expected_identities` (passed to `decide_resume`) has the exact ordered
keys:

```
requirement_id
selection_manifest_digest
row_identity_digest
claim_intent_digest
claim_ack_digest
progress_id
verified_operation_plan_digest
```

All seven values are bare 64-char lowercase SHA-256 hex.

### 5.7 `icp.requirement-cleanup-plan.v1`

```
kind = "icp.requirement-cleanup-plan.v1"
schema_version = 1
requirement_id                              # sha256
terminal_status = "done" | "error"
writeback_ack_digest                        # sha256
sealed_evidence_digest                      # sha256 (required, not null)
actions          = ["remove-active-pointer",
                   "remove-progress",
                   "remove-scratch",
                   "verify-cleanup"]        # exact order
next_requirement_allowed = false            # fixed
```

### 5.8 `icp.requirement-cleanup-report.v1`

```
kind = "icp.requirement-cleanup-report.v1"
schema_version = 1
requirement_id                              # sha256
terminal_status = "done" | "error"
cleanup_verified               = true       # fixed when verification passes
checkpoint_evidence_retained   = true       # fixed
sealed_evidence_retained       = true       # fixed
next_requirement_allowed       = true       # fixed when verification passes
```

## 6. State machines

### 6.1 Crash-window recovery (`decide_claim_recovery`)

Decision rules, in order:

1. Invalid intent or expected identity mismatch -> raise
   `ClaimIntentError`; never produce an actionable report.
2. `observed_status="empty"` and observed SHA equals
   `source_sha256_before` -> `retry-cas / row-empty-before-sha-match`.
3. `observed_status="doing"` and observed SHA equals
   `expected_source_sha256_after` ->
   `reconstruct-claim-ack / row-doing-after-sha-match`.
4. SHA mismatch (empty or doing, observed SHA does not equal the
   matching expected) -> `blocked / source-sha-mismatch`.
5. `done | error | unknown` -> `blocked / unexpected-row-status`.

`decide_claim_recovery` only returns the controlled decision report;
it never embeds the full claim ack or any task path. P3d's
TaskSource-specific recovery API reconstructs and persists the ack from
the immutable claim-intent document when this report says
`reconstruct-claim-ack`.

### 6.2 Resume (`decide_resume`)

In order:

1. Zero active pointers, no orphan `progress`, no orphan `receipts` ->
   `new-selection-allowed / no-active-state`. Zero active pointers with
   an orphan `progress` or any receipt -> `blocked / no-active-state`.
2. More than one active pointer -> `blocked / multiple-active-pointers`.
3. Exactly one active pointer but lock not acquired ->
   `blocked / lock-not-acquired`.
4. Active pointer fails `verify_active_requirement` or any of
   `requirement_id`, `selection_manifest_digest`,
   `row_identity_digest`, `claim_intent_digest`, `claim_ack_digest`,
   `progress_id` differs from `expected_identities` ->
   `blocked / identity-mismatch` (or `progress-tamper` when the active
   document itself is malformed).
5. `observed_row_status` in `{done, error}` ->
   `terminal-cleanup-required / row-terminal`.
6. `observed_row_status` not `doing` -> `blocked / row-not-doing`.
7. Prerequisites `missing` -> `needs-user-input / prerequisites-missing`
   (preserves active state; no new step is started).
8. Prerequisites `blocked` -> `blocked / prerequisites-blocked`.
9. Missing progress -> `blocked / progress-missing`.
10. Progress fails `verify_progress` or its `requirement_id`,
    `progress_id`, `claim_ack_digest`, `verified_operation_plan_digest`
    differ from active / `expected_identities` ->
    `blocked / progress-tamper` or `blocked / identity-mismatch`.
11. Receipt chain fails `verify_checkpoint_chain` ->
    `blocked / receipt-chain-tamper`.
12. `progress.phase = terminal-pending` ->
    `terminal-cleanup-required / terminal-pending`.
13. First non-`done` feature in sorted order:
    - `started`, `replay_policy = none` ->
      `blocked / started-without-replay`;
    - `started`, `replay_policy = idempotent` ->
      `replay-step / replay-idempotent`;
    - `started`, `replay_policy = deterministic-recovery` ->
      `run-recovery-verifier / recovery-verifier-required`;
    - `pending` or `checkpointed` with a valid `next_step_id` ->
      `resume-step / resume-next-step` (status alone never authorizes
      a skip);
    - `failed`, or pending/checkpointed without a valid `next_step_id`
      -> `blocked / active-present` (no authorized next action).

A new selection is allowed only when there are zero active pointers and
no orphan progress/receipts. One active pointer always takes priority
over a new selection. With active state, the row must remain `doing`;
`done | error` requires terminal cleanup, not a new selection. A
`started` step is never silently skipped.

### 6.3 Terminal cleanup (`plan_terminal_cleanup`, `verify_terminal_cleanup`)

`plan_terminal_cleanup` fails closed unless:

- `active` and `progress` each pass their verifier and share
  `requirement_id`;
- `progress.phase = terminal-pending`;
- `terminal_status` is `done` or `error`;
- `writeback_ack_digest` is bare SHA-256 hex and equals
  `expected_writeback_ack_digest`;
- `sealed_evidence_digest` is bare SHA-256 hex (not null).

On success it returns the immutable `icp.requirement-cleanup-plan.v1`
with the fixed action order and `next_requirement_allowed = false`.

`verify_terminal_cleanup` fails closed unless `active`, `progress`, and
scratch are all absent, the checkpoint-chain digest is unchanged, and
the sealed evidence digest after cleanup equals the plan's
`sealed_evidence_digest`. On success it returns the immutable
`icp.requirement-cleanup-report.v1` with every boolean true and
`next_requirement_allowed = true`. Neither function performs unlink or
deletion; P3d executes the fixed action IDs and feeds the verified
observations back.

## 7. P3a2 / P3d boundary

P3a2 owns:

- canonical schema, ordered keys, enums, and types for the eight kinds;
- canonical-bytes / digest and identity derivations;
- pure fail-closed verifiers (`verify_*`);
- pure decision state machines (`decide_claim_recovery`,
  `decide_resume`, `plan_terminal_cleanup`, `verify_terminal_cleanup`);
- the locked, immutable active pointer shape.

P3d owns:

- publishing and persisting the claim-intent document, active pointer,
  mutable progress, and immutable checkpoint receipts under atomic
  no-clobber / atomic-replace disciplines;
- the real `flock` / state-root exclusive lock that produces
  `exclusive_lock_acquired`;
- TaskSource-specific crash-window CAS, claim-ack reconstruction, and
  writeback CAS;
- scratch creation and the actual unlink / removal of the active
  pointer, mutable progress, and scratch (never of checkpoint receipts,
  screenshot provenance, visual diff, or sealed evidence);
- observing and feeding back `checkpoint_chain_digest_before/after`,
  `sealed_evidence_digest_after`, and `active/progress/scratch_present`;
- wiring the requirement / claim-intent / progress identities through
  platform binding / authorization / executor request scopes.

P3a2 never weakens a schema, never embeds a path or full claim ack, and
never bypasses P3d's CAS / lock / persistence.

## 8. Stop rules

The P3a2 contract must stop (refuse to expand scope) whenever any of the
following would be required to make the contract correct. This stop
discipline keeps P3a2 a pure, schema-only, task-source-neutral layer;
production effects and platform / TaskSource wiring belong in a
separate, separately-approved phase.

Stop without expanding scope if:

- correctness would require editing an existing ICP file;
- the contract would need to import a TaskSource, platform, vendor,
  registry, or production publisher module;
- the contract would need to perform a filesystem, lock, CAS,
  subprocess, network, write, or unlink effect;
- the active pointer would have to embed a path, mutable progress
  digest, lifecycle flag, full claim ack, or any task content;
- a decision report would have to embed a path, full claim ack, row
  title, task reference, source contents, secret, or arbitrary
  exception text;
- a schema field would have to be weakened (extra optional field,
  widened enum, missing identity binding, reordered keys, accepted
  injection field);
- a feature would have to ship P3b1 / P3d behavior (production
  readiness gate, resolver, freezer, claim/writeback, executor wiring,
  scratch deletion, real receipt persistence).

P3a2 implements only the pure requirement-resume contracts above. Any
expansion belongs in a separate, separately-approved phase.
