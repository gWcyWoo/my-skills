---
name: icp
description: ICP = Client Page. Implement or revise one externally claimed client page or one multi-page client flow from canonical IOLE JSON and Lanhu/Figma evidence. The caller owns Sheet polling, role state, flow claim/lease, worktree, Git/PR, and writeback; ICP owns component reuse analysis, a serial worker DAG, client code, full-flow verification, evidence, and a ready-for-PR handoff.
---

# ICP — Client Page

ICP consumes one canonical external client page or flow job. IOLE already owns the
selected client role lease and an isolated Git worktree. ICP never polls Excel,
selects or claims rows, mutates task status, commits, pushes, creates a PR, or writes
URLs back.

## Multi-page flow v5

For every new `icp.external-flow-job.v5`, read
[flow-job-contract-v5.md](references/flow-job-contract-v5.md),
[flow-job-contract-v4.md](references/flow-job-contract-v4.md),
[implementation-contract-v1.md](references/implementation-contract-v1.md),
[page-graph-contract-v1.md](references/page-graph-contract-v1.md),
[component-reuse-contract-v1.md](references/component-reuse-contract-v1.md), and
[worker-node-contract-v2.md](references/worker-node-contract-v2.md), plus
[visual-verification-contract-v1.md](references/visual-verification-contract-v1.md)
for every page node.

Require component inventory evidence before implementation. Keep the interaction
graph separate from the implementation DAG. Execute shared-component edits first,
then modified leaf pages, then parents/navigation, and finally main-agent E2E.
Require one non-overlapping owner for every changed path.

Use prepare, next-node, record-contract, record-node, and finalize.
Handle `next-node` exactly:

- `contract-compilation-required`: remain in the main ICP session, read the
  returned compiler prompt/input, inspect current public project contracts
  read-only, fetch each exact design once, and compile the full implementation
  contract before any test or production edit. Existing project behavior or an
  explicit user decision that truly applies but is absent from Sheet/design must
  be a provenance-backed task-local `context_source_clause`; never turn it into a
  universal platform capability. Pass `record-contract`. Do not spawn an
  implementation child yet.
- `ready`: spawn exactly one child agent with the returned `worker_prompt`; wait
  for that child to finish before dispatching another node.
- `resume-required`: resume the same child task from its persisted prompt/result
  paths; never start another node.
- `blocked`: stop the flow and return its controlled node failure to IOLE.
- `ready-for-finalize`: run main-agent full-flow verification and finalize.

Every child agent must invoke and follow `$icp` for its one node; loading the Skill
hash alone is not compliance. The main ICP session, not an implementation child,
has already frozen public targets, ownership, source clauses, exact acceptance
cases, TDD slices, and the complete design-state matrix. A child consumes only its
bound IDs and implements them in serial integration-contract-first RED-GREEN
slices, then runs the measured root-cause loop in the visual contract.
An intermediate mismatch is diagnostic evidence, not a worker result. Keep
repairing one classified root cause at a time while the same metric improves.
Only a real external/contract blocker or two consecutive no-progress repairs for
the same target may return `status=failed`.

The page child writes `icp.worker-node-result.v2` with exact clause evidence only
after every state passes anchors and regional pixels in two independent
capture/reset runs sealed by
`icp.visual-verification.v1`. Behavior tests or one global pixel comparison cannot
make a page pass. The main agent rejects any contrary result immediately.

Shared-component and integration children still edit only their `allowed_paths`
and run focused tests/self-check. No child reads or writes Sheet/Excel state, lease
fields, Git, commits, branches, pushes, or PRs. Validate and record each result
before continuing.

After every node passes, the main ICP agent runs trusted full-flow tests, real
browser/simulator/emulator capture, visual comparison, and E2E. Seal the four
artifacts in `icp.flow-evidence-manifest.v1`; the exact union of worker-declared
changed files becomes the flow handoff. Return only
`icp.flow-handoff-result.v2/ready-for-pr` with computed exact clause coverage. IOLE alone owns Git/PR and multi-row
`review` writeback.

Every v5 member contains an exact `source_contract` generated from mapping-declared
Sheet job fields. Treat it as authoritative over every derived view. Preserve its
copy, lists, newlines, whitespace, Unicode, and empty mapped sections exactly;
never replace it with a summary or read Sheet state to reconstruct it. ICP verifies
the source-contract digest, reconstructs every derived member field, recomputes the
member digest, and fails before node dispatch on any mismatch. Continue accepting
`icp.external-flow-job.v3` and v4 only for persisted legacy flows; never migrate
their saved state in place.

## Single-page v2 compatibility

Require one absolute JSON job path. New IOLE calls use exactly this v2 shape:

```json
{
  "kind": "icp.external-page-job.v2",
  "schema_version": 2,
  "job_id": "iole:client:row-42:review-2:64-lowercase-sha256-prefix",
  "row_digest": "64-lowercase-sha256",
  "project_root": "/absolute/path/to/job-worktree",
  "base_revision": "git-commit-sha",
  "platform": "nextjs",
  "profile": "nextjs-standard",
  "design_source": "lanhu-figma",
  "design_ref": "design locator",
  "role": "client",
  "mode": "revise",
  "review": {
    "number": 2,
    "text": "点击按钮没有跳转"
  },
  "page": {
    "title": "Loan home",
    "route": "/",
    "requirement": "Implement the supplied page design.",
    "acceptance_criteria": ["Matches the supplied design."]
  }
}
```

Require `role=client`. `mode=implement` requires `review=null`; `mode=revise`
requires one positive numbered review with non-empty text. IOLE derives a distinct
job ID for each latest review number and supplies the existing PR-head worktree for
revision. Continue accepting `icp.external-page-job.v1` only for persisted legacy
jobs. `page.acceptance_criteria` may be an empty list when the Sheet's `UT`, `IT`,
and `E2E` cells are all empty. ICP's own page tests, runtime capture, and visual
verification remain mandatory.

IOLE normalizes the Sheet row into this contract. Do not interpret workbook column
names inside ICP and do not accept raw status, PR, lease secret, command, executable,
or runtime override fields.

Interpret `page.route` by platform while preserving the v1 field name:

- Next.js and Vue require a non-empty absolute route beginning with `/`.
- Flutter, iOS, and Android require a non-empty page, screen, or component target
  identifier; they do not require `/`.
- Do not register native navigation solely because a target identifier is present.
  When the title and requirements describe a reusable component, implement that
  component and use an existing preview, host screen, or test harness for runtime
  verification instead of inventing a production route.

Run the lightweight page-job preparation command:

```bash
ICP=~/.agents/skills/icp
PYTHONDONTWRITEBYTECODE=1 \
python3 "$ICP/scripts/icp_page_job_v1.py" prepare \
  --job /absolute/path/job.json
```

Handle the decision exactly:

- `ready`: implement this page.
- `resume-required`: resume this same job and do not start another page.
- `blocked/input-drift`: stop; the upstream row changed for an existing `job_id`.
- `invalid-input`: stop and return the controlled reason to the upstream caller.

Preparation performs only strict job validation, fixed platform/profile lookup,
worktree HEAD verification, and local job identity persistence. It must not perform
CSV access, dependency installation, design download, browser/device probing, row
claim, writeback recovery, or terminal cleanup.

## Page implementation workflow

After `ready` or `resume-required`:

1. Load the persisted canonical job from the returned state root.
2. For `implement`, build the requested page. For `revise`, preserve correct
   existing code and make the smallest change that satisfies the supplied latest
   review; do not perform an unrelated redesign.
3. Fetch and normalize only the supplied `design_ref` when the design step begins.
4. Define the public target/ownership boundary and exact observable visual-state
   matrix; analyze layout, typography, assets, responsive behavior, and states.
5. Implement only the requested page target in the supplied worktree using the
   selected platform's existing page, navigation, or component conventions.
6. Package page assets and fonts with platform-native configuration.
7. Run focused page tests and the minimum build/type gate needed for the page.
8. Capture the real page from a browser, simulator, or emulator when verification
   reaches runtime capture. Never use the design image as the implemented UI.
9. Calibrate capture, take a baseline, then classify and repair one root cause per
   measured iteration while the target metric improves. Pass only after anchors
   and regional pixels are green in two independent capture/reset runs; use the
   visual contract's controlled failure boundary for blockers or repeated
   no-progress.

Design access, platform tools, dependencies, and capture runtime are checked at the
step that uses them, not in a monolithic startup preflight. A step failure becomes a
controlled page-job result for the upstream scheduler; ICP does not mutate Excel.

## Handoff contract

When the page and all three verification categories pass, create the exact
`icp.page-evidence-manifest.v1` defined in
[page-job-contract-v2.md](references/page-job-contract-v2.md). Bind it to this job
ID and job digest. Its three distinct non-empty artifacts must be real files below
this job's state root, and runtime capture must declare the platform's real
browser/simulator/emulator screenshot source. Record and verify each artifact's
SHA-256; finalization also seals the manifest SHA-256 into the result. Then create
a handoff input:

```json
{
  "kind": "icp.page-handoff-input.v1",
  "schema_version": 1,
  "status": "ready-for-pr",
  "changed_files": ["app/page.tsx"],
  "verification": {
    "page_tests": "passed",
    "runtime_capture": "passed",
    "visual": "passed"
  },
  "evidence_manifest": "/absolute/job-state/evidence-manifest.json"
}
```

Every changed file must be a real non-symlink file under `project_root`. The evidence
manifest must be a real non-symlink file under this job's state root. Finalize with:

```bash
PYTHONDONTWRITEBYTECODE=1 \
python3 "$ICP/scripts/icp_page_job_v1.py" finalize \
  --job /absolute/path/job.json \
  --handoff /absolute/path/handoff.json \
  --result /absolute/path/result.json
```

The result is `icp.page-handoff-result.v1`. It contains job identity, base revision,
project root, changed files, verification, and evidence. It never contains PR or
status URLs. IOLE alone commits, pushes, creates or reuses the PR, and writes
all row status/URL fields.

## Page-job state and stop rules

State lives under `<project_root>/.icp/page-jobs/<sha256(job_id)>/`.

- Same `job_id` and identical canonical input resumes the existing job.
- Same `job_id` with different input is blocked as `input-drift`.
- Identical finalization is idempotent and never overwrites the result.
- A changed file outside the worktree, missing evidence, or any failed verification
  blocks `ready-for-pr`.
- Never operate on a second job in the same worktree.
- Never invoke `icp_entry_v1.py`, `icp_begin_requirement_v1.py`, CSV selection,
  claim, terminal writeback, or PR tooling for the current page-job workflow.

Active IOLE contract: `references/page-job-contract-v2.md`. Legacy v1 compatibility:
`references/page-job-contract-v1.md`.

## Legacy managed-CSV implementation

The remaining managed-CSV material below is retained only for compatibility and
historical verification. Ignore it unless the user explicitly requests legacy CSV
orchestration. It is not the default ICP workflow.

## Invocation contract

Require one absolute JSON config path. The document has exactly these keys:

```json
{
  "task_source": "csv",
  "task_ref": "/absolute/path/tasks.csv",
  "design_source": "lanhu-figma",
  "platform": "vue",
  "project_root": "/absolute/path/project",
  "profile": "vue-vite"
}
```

Supported platform/profile pairs:

| platform | profile | execution state | actual evidence |
|---|---|---|---|
| `flutter` | `flutter-standard` | active | simulator screenshot |
| `vue` | `vue-vite` | active | browser screenshot |
| `nextjs` | `nextjs-standard` | active | browser screenshot |
| `ios-swift` | `ios-swift-standard` | active | simulator screenshot |
| `ios-objc` | `ios-objc-standard` | active | simulator screenshot |
| `android-java` | `android-java-standard` | active | emulator screenshot |
| `android-kotlin` | `android-kotlin-standard` | active | emulator screenshot |

Never synthesize a package, profile, activation, executable, toolchain, device, or
runtime override. Only the fixed registry and verified package descriptor may select
execution code.

## Mandatory entry gate

This is the user-attended intake phase of a long task. First confirm the requested
`platform`/fixed `profile`, task source, design source, and project root. Then keep
rerunning the gate with the user until it returns `ready`, `resume-required`,
`no-work`, or `blocked`. Do not let the user leave on `needs-user-input`.

Run this before selection, design fetch, manifest creation, or claim:

```bash
ICP=~/.agents/skills/icp
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ICP/scripts" \
python3 "$ICP/scripts/icp_entry_v1.py" --config /absolute/path/run-config.json
```

Handle the machine result exactly:

- `needs-user-input`: show every `missing_inputs` item in returned order, including
  deferred runtime checks, and stop. Every item must belong to the selected platform
  or shared CSV/design/core checks. Do not claim.
- `blocked`: explain the controlled blocker and stop. For
  `platform_package_activation`, the installed package/index is inconsistent; repair
  and re-verify it before claim. For `orphan_doing_without_state`, recover or resolve
  the existing CSV ownership before selecting another row.
- `resume-required`: resume the persisted requirement and exact `step_id`. Do not
  freeze a new selection and do not claim another row. When
  `unattended_ready=true`, continue without another user wait.
- `no-work`: stop successfully without installing platform dependencies, creating
  state, or claiming a row.
- `ready`: require `unattended_ready=true`, then continue the sequence below without
  another user wait.

Entry must prove, before claim:

1. config and fixed registry/profile/package resolution;
2. canonical non-symlink project root and required platform toolchain;
3. regular writable CSV, one empty-status candidate, and stable source digest;
4. valid and accessible Lanhu/Figma locator for that candidate;
5. all project dependencies needed later in the long task;
6. a real capture runtime (`Chrome`, simulator, or emulator as applicable);
7. no unfinished active requirement, pending claim, checkpoint recovery, writeback,
   or terminal cleanup.

Platform prerequisites are conditional: npm is checked only for selected Vue/Next.js,
Xcode only for selected iOS, and Java/ADB only for selected Android. For Vue,
`package-lock.json`, installed Vue/Vite/Vitest/Playwright dependencies, and Google
Chrome are mandatory. Missing installation is remediated with `npm ci` before claim.

Flutter, Next.js, iOS, and Android projects must also provide the exact
`<project_root>/.icp/platform-config.json` shape owned by the selected platform:

- Flutter: `device_id`;
- Next.js: `route`, `viewport_width`, `viewport_height`;
- iOS: `project`, `scheme`, `simulator_udid`, `app_product`, `bundle_id`;
- Android: `module`, `variant`, `device_serial`, `application_id`, `activity`,
  `apk_path`.

The entry gate validates the selected simulator/emulator is currently available.
Missing or invalid fields are user-owned missing inputs and must be resolved before
claim.

## P2e2a — Flutter authorization boundary

Authorization prepare/verify transitively re-run the fixed read-only Flutter
version preflight (`flutter --version --machine`) through the shared binding
verifier. This layer never directly executes an operation-plan command.

## P2e2b — Flutter executor boundary

Immediately before spawn, executor re-verification transitively re-runs the
fixed read-only Flutter preflight (`flutter --version --machine`) through the
shared binding/authorization verifier chain. The preflight subprocess belongs
to the project-preflight component, outside the executor's operation-plan spawn
surface. Executor-owned environment construction is policy and is not bound by
P2e2a; the supervisor process environment remains trusted input. Executable,
script, and working-directory paths are rechecked immediately before spawn, but
a TOCTOU residual remains: verification plus subprocess spawn does not eliminate
the verify-to-spawn race.

## P3b1a — entry readiness

Readiness aggregates common and platform entry probes before any TaskSource
mutation. Missing user-owned input returns `needs-user-input`; environmental or
integrity failure returns a controlled blocker.
Active contract: `references/runtime-contract-v1.md`. The pure readiness schema is
implemented by `scripts/entry_readiness_v1.py`; `references/entry-readiness-v1.md`
is its historical phase contract.

## P3b1b — package-aware entry seam

Order is fixed: entry readiness → active-first resume decision → package-aware
support gate → TaskSource/manifest/claim. An inactive or non-executable package
stops at the gate with zero claim and zero adjacent publication. Every active package
must still pass module, descriptor, transitive dependency, registry, and profile
digest verification before this gate returns success.
P3d durable orchestration preserves this ordering across resume and recovery.
`references/p3-platform-package-architecture.md` is the historical migration plan,
not the current activation status.

## New requirement sequence

Only after the entry result is `ready`:

1. Acquire the stable state-root exclusive lock.
2. Re-run terminal-cleanup and pending-claim recovery. Active state wins.
3. Select exactly one highest-priority empty-status CSV row.
4. Freeze `selection-manifest.json` without changing its v1 schema.
5. Publish adjacent `entry-readiness.json` and
   `platform-package-selection.json` with no-clobber writes.
6. Derive `requirement_id` from selection-manifest digest plus row-identity digest.
7. Persist the immutable claim intent and execution scope before CSV CAS.
8. CAS the row from empty to `doing`. On restart, retry the pre-CAS state or
   reconstruct the exact post-CAS claim ack.
9. Publish immutable active pointer plus revision-0 progress. Never prepare or
   claim a second requirement.

The implementation API is
`orchestrate_client_project_v1.prepare_single_requirement_with_entry_gate(...)`.
It fixes `limit=1`; callers cannot widen the batch.

Use the gated activation bridge instead of hand-building those API arguments:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ICP/scripts" \
python3 "$ICP/scripts/icp_begin_requirement_v1.py" \
  --config /absolute/path/run-config.json \
  --feature-positions /absolute/path/verified-feature-positions.json \
  --verified-operation-plan-digest 64-lowercase-sha256
```

The bridge reruns entry readiness immediately before activation. A non-`ready`
result never reaches claim preparation.

## Resume and checkpoint rules

Always load state under `RequirementStateStore.exclusive_lock()` before doing work.
Use `decide_stored_resume(...)`; never infer progress from generated files alone.

- `resume-step`: execute the returned `feature_id`/`step_id`.
- `replay-step`: run the same idempotent step; never skip it.
- `run-recovery-verifier`: verify deterministic recovery before continuation.
- `needs-user-input`: preserve active/progress/receipts and stop before a new step.
- `terminal-cleanup-required`: recover writeback/cleanup; do not select a row.
- `blocked`: preserve evidence and surface the exact reason.

Before a side-effecting step, replace progress to `started` with an explicit replay
policy. After success, create one immutable `icp.checkpoint-receipt.v1` and commit
it together with revision+1 progress through `commit_checkpoint(...)`. The pending
checkpoint journal makes receipt publication plus progress replacement restart-safe.

## Implementation loop

For each requirement, preserve the design-compiler workflow:

1. Fetch and normalize the design bundle; validate reference image, layout facts,
   assets, fonts, states, and requirement contract.
2. RED: add the smallest unit/integration/visual test for the current feature step.
3. GREEN: run the selected platform operation plan through verified binding and
   supervisor authorization.
4. Package assets/fonts/dependencies using platform-native configuration.
5. Assemble the feature, then perform serialized fan-in for shared routes or project
   files with compare-and-swap guards.
6. Run unit, integration/e2e, build/lint/project gates.
7. Capture a real runtime screenshot. `actual.png` may only come from a real
   browser/simulator/emulator capture; never use the design image as UI or actual.
8. Produce provenance and visual diff evidence, then checkpoint.

Flutter requirement scope and checkpoint receipts are wrapped by
`platforms/flutter_requirement_execution_v1.py`. Vue implements all eight operation
actions, including real Vite/Chrome capture and `actual_source=browser_screenshot`.
Next.js implements fixed npm/Chrome execution. iOS Swift/Objective-C use fixed
Xcode/simctl execution and simulator screenshots. Android Java/Kotlin use fixed
Gradle/ADB execution, UIAutomator traces, and emulator screenshots. Their shared
controlled executor is nonce-authorized, no-clobber, replay-safe, and restricted to
the project `.icp/runs/<batch>` state root.

## Terminal transition

1. Require all features `done` before a `done` writeback. `error` retains failure
   evidence.
2. Replace progress to `terminal-pending`.
3. Persist the terminal writeback transaction before `doing → done|error` CAS.
4. Execute or reconstruct the exact writeback ack after restart.
5. Seal checkpoint chain, screenshot provenance, visual diff, gate results, and
   terminal ack digest.
6. Persist the cleanup transaction, then remove only active pointer, mutable
   progress, and requirement scratch.
7. Retain claim intent, execution scope, checkpoint receipts, terminal transaction,
   sealed evidence, cleanup transaction, and completion report.
8. Only a verified cleanup report with `next_requirement_allowed=true` permits the
   next entry preflight and next row.

Use `finalize_active_csv_requirement(...)` for writeback, sealing, and cleanup.

## Ownership map

Shared, platform-independent:

- `scripts/icp_entry_v1.py`
- `scripts/icp_begin_requirement_v1.py`
- `scripts/csv_task_source.py`
- `scripts/entry_readiness_v1.py`
- `scripts/requirement_claim_intent_v1.py`
- `scripts/requirement_progress_v1.py`
- `scripts/orchestrate_client_project_v1.py`
- `scripts/freeze_selection_manifest.py`
- `scripts/platform_package_resolver_v1.py`
- `scripts/freeze_platform_package_selection_v1.py`
- `scripts/verify_platform_package_selection_v1.py`
- `scripts/design_sources/**`, `scripts/shared_core/**`

Platform-owned:

- `scripts/platforms/*_package_v1.py`
- `scripts/platforms/*_standard_v1.py`
- `scripts/platforms/*_project_preflight_v1.py`
- `scripts/platforms/*_operations_v1.py`
- platform binding/authorization/executor modules

Frozen contracts and detailed phase evidence live under `references/`, including
`implementation-history.md`. Read only the reference needed for the active issue.

## Stop rules

Stop without claim or new effects when:

- any entry material is missing or access is unverified;
- package/index/module/readiness/manifest digest drifts;
- package is inactive or non-executable;
- state lock is unavailable, multiple active/pending records exist, or identities
  differ;
- a started step has no authorized replay/recovery policy;
- actual screenshot provenance is not a real runtime capture;
- terminal evidence is unsealed or cleanup would delete audit receipts;
- completing ICP would require editing `iff/**`.

## Verification

Focused phase checks:

```bash
ICP=~/.agents/skills/icp
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ICP/scripts"
python3 "$ICP/scripts/selftest_entry_v1.py"
python3 "$ICP/scripts/selftest_flow_job_v1.py"
python3 icp/scripts/selftest_p3b1_entry_readiness.py
python3 "$ICP/scripts/selftest_p3d_shared_orchestrator.py"
python3 "$ICP/scripts/selftest_p3d_requirement_resume_integration.py"
python3 "$ICP/scripts/selftest_p3d_flutter_parity.py"
python3 "$ICP/scripts/selftest_p3e_vue_parity.py"
python3 "$ICP/scripts/selftest_p4_platform_packages.py"
```

Before handoff, run every `selftest_*.py`, fixed package/index verification,
`verify_vendor_iff_v1.py`, the frozen `iff` baseline/diff checks, skill validation,
and confirm no `__pycache__`/`.pyc` remains.
