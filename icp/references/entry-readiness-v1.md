# ICP P3b1a Entry Readiness + Active-First Gate v1 Contract

Status: pure, in-memory contract only. Every platform remains
`inactive`; P3b1a does not perform filesystem I/O, locking, CAS,
subprocess, network, write, claim, writeback, scratch cleanup, probe
execution, package selection, or production artifact publication.
This reference is the canonical P3b1a contract authored for the
entry-readiness slice; it is not a byte copy of any external file.

## 1. Scope

P3b1a freezes only the pure data + decision layer for the entry gate:

- the canonical schema and fail-closed verifiers for the three
  P3b1a document kinds;
- the canonical-bytes / SHA-256 digest derivation;
- the pure readiness aggregator (`aggregate_readiness`);
- the pure active-first entry-gate state machine (`decide_entry`);
- the fixed, platform-neutral core readiness-requirement matrix;
- the closed secure-supply channel mapping for user-input redaction.

P3b1a performs:

- zero filesystem I/O, locking, CAS, subprocess, network, write, or
  unlink/cleanup;
- zero production claim, writeback, receipt persistence, scratch
  creation, probe execution, or artifact publication;
- zero package selection / activation; the descriptor is supplied by
  the caller and only validated.

`exclusive_lock_acquired`, `observed_row_status`, `candidate_count`,
and the supplied descriptor / observations / active state are verified
P3b1b / P3d inputs; this module never inspects a filesystem, executes
a probe, or selects a package itself.

## 2. P3b1a / P3b1b / P3d boundary

P3b1a owns:

- canonical schemas, ordered keys, enums, and types for the three
  document kinds;
- canonical-bytes / digest derivation;
- pure fail-closed verifiers (`verify_observation`,
  `verify_readiness_report`, `verify_entry_gate_decision`);
- the pure readiness aggregator and active-first entry gate state
  machine;
- the locked, fixed core readiness-requirement matrix and the closed
  secure-supply channel mapping.

P3b1b (later, separately approved) owns:

- the fixed package resolver / selection (mapping `(platform,
  profile)` to a fixed package module basename / SHA index);
- production entry wiring (calling probes, building observations,
  supplying the descriptor, source snapshot / candidate identity
  digests);
- the registry-aware support gate that runs before any TaskSource
  access;
- the adjacent ready-only `entry-readiness.v1.json` publication
  semantics.

P3d (later, separately approved) owns:

- filesystem publishing, the real `flock` / state-root exclusive
  lock, CAS, claim / writeback, scratch cleanup, checkpoint-receipt
  persistence, and platform binding / authorization / executor
  wiring;
- observing and feeding back `active_present` / `progress_present` /
  `scratch_present`, `checkpoint_chain_digest_before/after`, and
  `sealed_evidence_digest_after`;
- wiring the requirement / claim-intent / progress identities through
  platform binding / authorization / executor request scopes.

P3b1a never weakens a schema, never embeds a path or full claim ack,
never executes a probe, never selects a package, and never bypasses
P3b1b's resolver or P3d's CAS / lock / persistence.

## 3. Canonical kinds

| Kind | Owner module |
|---|---|
| `icp.entry-readiness-observation.v1` | `icp/scripts/entry_readiness_v1.py` |
| `icp.entry-readiness-report.v1` | `icp/scripts/entry_readiness_v1.py` |
| `icp.entry-gate-decision.v1` | `icp/scripts/entry_readiness_v1.py` |

## 4. Public API

### 4.1 Module `icp/scripts/entry_readiness_v1.py`

```
EntryReadinessError(ValueError)
document_digest(document: dict) -> str
verify_observation(document: dict) -> None
verify_readiness_report(document: dict) -> None
verify_entry_gate_decision(document: dict) -> None
aggregate_readiness(
    *,
    resolved_config_digest: str,
    package_descriptor: dict,
    task_source_id: str,
    design_source_id: str,
    task_source_snapshot_digest: str,
    candidate_identity_digest: str,
    candidate_count: int,
    observations: list[dict],
) -> dict
decide_entry(
    *,
    readiness_report: dict,
    active_pointers: list[dict],
    progress: dict | None,
    receipts: list[dict],
    expected_identities: dict,
    exclusive_lock_acquired: bool,
    observed_row_status: str,
) -> dict
```

Local error class: `EntryReadinessError(ValueError)`.

The module uses only the Python standard library (`hashlib`,
`importlib.util`, `json`, `sys`, `pathlib`, `typing`) and lazily
loads two existing in-tree contracts via private aliases:

- `icp/scripts/platforms/platform_package_contract_v1.py`
  (the platform-neutral P3a descriptor validator + digest helper);
- `icp/scripts/requirement_progress_v1.py`
  (the P3a2 requirement-resume contract and `decide_resume` state
  machine).

No CLI, no import-time I/O, no `if __name__ == "__main__"` block, no
public constants, no platform-specific imports / branches / literals /
package-specific IDs.

## 5. Canonical bytes and digest derivation

Canonical bytes for every document:

```python
(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
```

`document_digest(document) = sha256(canonical_bytes(document))`.
Documents contain no self-referential digest field. Every identity and
digest field is a bare 64-character lowercase SHA-256 hex string.

## 6. Document schemas

For every kind, keys must appear in the exact order listed, with the
exact type / enum / nullness described. Unknown keys, missing keys,
duplicate keys, reordered keys, malformed values, and forbidden
injection keys (see section 11) fail closed at every nesting level.

### 6.1 `icp.entry-readiness-observation.v1`

```
kind = "icp.entry-readiness-observation.v1"
schema_version = 1
probe_id                         # safe ID, lowercase [a-z0-9._-], 1..128
status = "pass" | "missing" | "blocked" | "deferred"
evidence_digest = sha256 | null
reason_code = safe-id | null
blocked_by = []                  # sorted unique safe requirement IDs
```

Rules:

- `pass`: non-null `evidence_digest`; `reason_code=null`;
  `blocked_by=[]`.
- `missing`: `evidence_digest=null`; non-null `reason_code`;
  `blocked_by=[]`.
- `blocked`: non-null `reason_code`; `evidence_digest` may be sha256
  or null; `blocked_by=[]`.
- `deferred`: `evidence_digest=null`; non-null `reason_code`;
  non-empty sorted unique `blocked_by`.

The input observation list supplied to `aggregate_readiness` must be
strictly sorted and unique by `probe_id`; duplicates, unknown
probe_ids (not referenced by any requirement), or unsorted input fail
closed.

### 6.2 `icp.entry-readiness-report.v1`

```
kind = "icp.entry-readiness-report.v1"
schema_version = 1
status = "needs-user-input" | "blocked" | "no-work" | "ready"
resolved_config_digest                       # sha256
package_descriptor_digest                    # sha256 (computed by aggregate_readiness)
task_source_snapshot_digest                  # sha256
candidate_identity_digest                    # sha256
checks[]                       = {id, owner, status, evidence_digest}
missing_user_inputs[]          = {id, reason_code, accepted_shape_id,
                                  secure_supply_channel, sensitive}
deferred_checks[]              = {id, blocked_by}
blockers[]                     = {code, scope, evidence_digest,
                                  remediation_id}
```

`checks[]`:

- `id`: safe-id, the requirement ID (core or descriptor).
- `owner`: controlled vocabulary `user | source | environment |
  platform` (mirrors the P3a descriptor `entry_requirement.owner`).
- `status`: controlled vocabulary `pass | missing | blocked |
  deferred`.
- `evidence_digest`: sha256 or null. A `pass` check always carries
  evidence; other statuses may carry null.

`missing_user_inputs[]`:

- `id`: the missing requirement ID.
- `reason_code`: a controlled safe-id. For a synthetic missing
  observation (no input) the reason is `observation-missing`; for an
  explicit `missing` observation the reason mirrors the observation's
  own `reason_code`.
- `accepted_shape_id`: derived from the requirement metadata (core or
  descriptor).
- `secure_supply_channel`: derived from a closed mapping -- sensitive
  inputs use `channel.credential_supply`; non-sensitive inputs use
  `channel.user_supply`. No other channel IDs exist.
- `sensitive`: bool, derived from the requirement metadata.

`deferred_checks[]`:

- `id`: the deferred requirement ID.
- `blocked_by`: non-empty sorted unique safe IDs (the deferred
  dependency requirement IDs). Invalid (unknown) IDs are represented
  as `invalid-deferred-dependency` blockers, not here.

`blockers[]`:

- `code`: controlled vocabulary `unsupported-task-source |
  unsupported-design-source | invalid-deferred-dependency |
  blocked-observation`.
- `scope`: controlled vocabulary `task-source | design-source |
  source-compat | requirement`.
- `evidence_digest`: sha256 or null (null for source-compatibility
  blockers).
- `remediation_id`: safe-id; for source-compat blockers the closed
  values are `remediation.unsupported_task_source` and
  `remediation.unsupported_design_source`; for requirement-scope
  blockers the value comes from the requirement metadata.

All nested objects have exact ordered keys. All arrays are strictly
sorted and unique by their identity key (`id` for checks /
missing_user_inputs / deferred_checks; the full content tuple for
blockers). Duplicates, reordering, unknown fields, or malformed
values fail closed.

### 6.3 `icp.entry-gate-decision.v1`

```
kind = "icp.entry-gate-decision.v1"
schema_version = 1
decision = "select-new" | "resume-step" | "replay-step"
         | "run-recovery-verifier" | "needs-user-input"
         | "terminal-cleanup-required" | "blocked" | "no-work"
reason_code                    # safe-id
readiness_report_digest        # sha256 (digest of the verified readiness report)
resume_decision_digest         # sha256 (digest of the exact P3a2 resume decision)
requirement_id = sha256 | null
progress_id = sha256 | null
feature_id = safe-id | null
step_id = safe-id | null
checkpoint_receipt_digest = sha256 | null
```

The entry decision embeds only digests and controlled identity
fields. It never embeds the full readiness report, the full P3a2
resume decision, the full active pointer, the full progress document,
or any receipt body.

## 7. Fixed core readiness-requirement matrix

The aggregator always renders exactly four fixed, platform-neutral
core requirements. Their IDs, owners, required flag, sensitivity,
probe IDs, accepted-shape IDs, and remediation IDs are all closed
metadata. Package-specific requirements come only from
`package_descriptor.entry_requirements`.

| id | owner | required | sensitive | probe_id | accepted_shape_id | remediation_id |
|---|---|---|---|---|---|---|
| `core.task_source.access` | `source` | true | false | `core.task_source.access` | `shape.task_source_readable` | `remediation.supply_task_source_access` |
| `core.design_source.access` | `source` | true | true | `core.design_source.access` | `shape.design_source_credential_slot` | `remediation.supply_design_source_credential` |
| `core.project_root.access` | `user` | true | false | `core.project_root.access` | `shape.existing_directory_under_workspace` | `remediation.supply_project_root` |
| `core.state_root.atomic_write` | `environment` | true | false | `core.state_root.atomic_write` | `shape.atomic_write_capability` | `remediation.supply_state_root_atomic_write` |

The four owners cover the four P3a controlled owner values
(`user | source | environment | platform`) except `platform`, which
is reserved for descriptor-declared package-specific requirements
(e.g. toolchain presence). No project-specific or platform-specific
condition is added at the core layer.

Any requirement-ID collision between the core matrix and the
descriptor `entry_requirements` fails closed.

## 8. Descriptor requirement interpretation

`aggregate_readiness`:

1. Validates the supplied `package_descriptor` using the existing
   platform-neutral P3a validator
   (`platform_package_contract_v1.validate_descriptor`). Any
   descriptor shape / enum / ordering / injection violation raises
   `EntryReadinessError`.
2. Computes the descriptor digest itself
   (`platform_package_contract_v1.compute_descriptor_digest`) and
   binds it on the report.
3. For each fixed core requirement and each descriptor entry
   requirement, matches exactly one observation by `probe_id`.
   Absence becomes a deterministic synthetic
   `missing / observation-missing` check.
4. Rejects observations whose `probe_id` is not referenced by any
   requirement (extra / unknown observations fail closed).
5. Allows a shared `probe_id` to satisfy more than one descriptor
   requirement; never silently drops a requirement.

## 9. Source compatibility

`task_source_id` and `design_source_id` are caller-supplied
controlled safe IDs. The aggregator validates them as safe IDs, then
checks membership in the descriptor's `supported_task_sources` /
`supported_design_sources` lists.

Unsupported `task_source_id` / `design_source_id` becomes a
deterministic blocker (`unsupported-task-source` /
`unsupported-design-source`, scope `source-compat`) and forces the
overall status to `blocked`. This is a deterministic blocker, not an
exception: the exception path is reserved for malformed basic input
schemas (descriptor shape, observation shape, digest shape, etc.).

## 10. Precedence, sorting/dedup, digest binding, evidence rules

Overall report status precedence:

1. any blocker (`unsupported-task-source`,
   `unsupported-design-source`, `blocked-observation`) or invalid
   deferred dependency -> `blocked`;
2. any required missing check, or deferred check whose `blocked_by`
   points only to a missing requirement in this same report ->
   `needs-user-input`;
3. all required checks satisfied and `candidate_count == 0` ->
   `no-work`;
4. otherwise -> `ready`.

Optional missing requirements may remain visible in `checks` but do
not create `missing_user_inputs` entries and do not prevent
`ready` / `no-work`.

Every `pass` check must carry evidence. Observations with status
`pass` and `evidence_digest=null` fail closed.

The aggregator deduplicates blockers by their full content tuple
(`code`, `scope`, `evidence_digest`, `remediation_id`) and sorts them
deterministically. `checks`, `missing_user_inputs`, and
`deferred_checks` are strictly sorted and unique by `id`.

Identity digest drift: changing `resolved_config_digest`,
`task_source_snapshot_digest`, or `candidate_identity_digest` changes
the canonical report bytes and therefore the report digest. The
descriptor digest is recomputed by the aggregator on every call.

`aggregate_readiness` never mutates its inputs.

## 11. Forbidden injection keys

Rejected at every nesting level in every P3b1a document (observation,
report, entry-gate-decision):

```
command, argv, shell, interpreter, env, runner, args, program, cmd,
subprocess, exec, run, script_path, script_runner, activate,
activation_command, activation_override, prompt, prompt_template,
path, task_ref, row_title, design_url, secret, token, password,
credential, api_key, claim_ack, writeback_ack, row_payload.
```

Rejection is by exact dictionary key only. A forbidden word
appearing as part of a larger identifier (for example a value like
`design_url_handler`) is NOT rejected; only exact key matches fail.

## 12. User-input redaction and secure-supply channel behavior

The readiness report never echoes supplied secret / token / password /
credential values, never echoes `task_ref` / `row_title` /
`design_url`, and never echoes row contents. A missing required
check produces exactly one `missing_user_inputs` entry carrying only
controlled IDs:

- `secure_supply_channel = channel.credential_supply` when the
  underlying requirement is `sensitive=true`;
- `secure_supply_channel = channel.user_supply` when the underlying
  requirement is `sensitive=false`.

User-facing explanation is rendered by fixed SKILL templates from
these controlled IDs; source text is never injected into the report
or into any prompt.

## 13. Active-first state mapping to P3a2

`decide_entry` derives the P3a2 `prerequisites_status` solely from
the verified readiness report's overall status:

- `ready` -> `met`;
- `needs-user-input` -> `missing`;
- `blocked` -> `blocked`;
- `no-work` -> `met` only when there are zero active pointers; with
  any active pointer it is a contradictory active-readiness state and
  is mapped to `blocked` so the P3a2 state machine fails closed
  through `blocked / prerequisites-blocked`.

`decide_entry` calls the existing P3a2 `decide_resume` itself with
the raw active / progress / receipt inputs and the derived
`prerequisites_status`. It does NOT accept a caller-supplied resume
decision and does NOT duplicate or reimplement the P3a2 state
machine.

Active-first mapping:

- Any P3a2 decision other than `new-selection-allowed` wins over a
  new selection and is mapped without changing its reason or
  step-identity fields.
- `resume-step`, `replay-step`, `run-recovery-verifier`,
  `needs-user-input`, `terminal-cleanup-required`, and `blocked`
  keep the same decision literal.
- Only P3a2 `new-selection-allowed` may consult the report for a new
  route: `ready -> select-new`, `needs-user-input ->
  needs-user-input`, `blocked -> blocked`, `no-work -> no-work`.

Therefore more than one active pointer, orphan progress / receipts,
missing lock, identity mismatch, progress tamper, or receipt-chain
tamper remain P3a2 fail-closed decisions. Missing prerequisites
preserve active state and never select a new row. `no-work` with an
active pointer fails closed via `blocked / prerequisites-blocked`
rather than selecting a new row.

## 14. Stop rules

The P3b1a contract must stop (refuse to expand scope) whenever any of
the following would be required to make the contract correct. This
discipline keeps P3b1a a pure, in-memory, schema-only, platform- and
task-source-neutral layer.

Stop without expanding scope if:

- correctness would require editing an existing ICP file outside the
  four allowed P3b1a paths;
- the contract would need to import a TaskSource, platform tool,
  vendor capsule, registry, or production publisher module beyond
  the two named contracts (P3a descriptor + P3a2 progress);
- the contract would need to perform a filesystem, lock, CAS,
  subprocess, network, write, or unlink effect;
- a schema field would have to be weakened (extra optional field,
  widened enum, missing identity binding, reordered keys, accepted
  injection field, new requirement ID, or new secure-supply channel
  ID);
- a feature would have to ship P3b1b behavior (production readiness
  gate wiring, fixed package resolver / index, probe execution,
  source-snapshot / candidate identity derivation) or P3d behavior
  (claim / writeback, scratch cleanup, real receipt persistence,
  binding / authorization / executor wiring);
- a platform conditional (`if platform == ...`) or platform-specific
  literal would have to appear in the core contract source.

Any of the above triggers a versioned contract change (new
`schema_version` or a new canonical kind) rather than a silent
widening of v1.

## 15. Invariants summary

- Every P3b1a document carries exact ordered keys; reordering,
  missing, extra, or unknown fields fail closed.
- All nested arrays are strictly sorted and unique by their identity
  key; the full content tuple is the identity for blockers.
- All identity and digest fields are bare 64-char lowercase SHA-256
  hex.
- All safe IDs are lowercase `[a-z0-9._-]`, length 1..128.
- `aggregate_readiness` and `decide_entry` are deterministic and do
  not mutate their inputs.
- The module exposes no CLI, no public constants, and no
  platform-specific branch, literal, import, or package-specific ID.
- The module performs zero I/O at import time and zero I/O inside
  any public call; the two named local contracts are loaded lazily
  via private aliases.

P3b1a implements only the pure entry-readiness contracts above. Any
expansion belongs in a separate, separately-approved phase (P3b1b or
P3d).
