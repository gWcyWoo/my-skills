# ICP managed-CSV runtime contract v1 (legacy)

This legacy contract is retained for managed-CSV compatibility. The active default
contract is `page-job-contract-v1.md`.

## 1. Platform selection

The invocation must supply one platform and may supply its fixed profile. Supported
platforms are `flutter`, `vue`, `nextjs`, `ios-swift`, `ios-objc`,
`android-java`, and `android-kotlin`. The fixed registries resolve the profile and
package. No caller may inject a package module, executable, command, device, or
runtime override.

Platform prerequisites are conditional. A selected Next.js or Vue run may require
Node.js/npm; an iOS run may require Xcode; an Android run may require Java/ADB.
Dependencies from an unselected platform must never appear in the entry result.

## 2. User-attended entry phase

The user remains available until the entry result is terminal for intake. The entry
gate runs before manifest creation, design download, row claim, worker dispatch, or
other long work.

The gate must check:

1. fixed config/profile/package resolution;
2. CSV access, schema, stable snapshot, and same-directory atomic replacement;
3. next-row design locator access when a candidate exists;
4. selected package project root, project materials, toolchain, installed
   dependencies, runtime config, and runtime target;
5. unfinished requirement, claim recovery, checkpoint, writeback, and cleanup state.

The selected package owns its platform checks through
`inspect_entry_requirements(project_root)`. Shared entry code must not encode npm,
Flutter, Xcode, simulator, Gradle, Java, ADB, browser, or device rules.

`needs-user-input` returns every currently determinable missing item in stable order.
If another missing choice prevents a runtime probe, the deferred runtime check is
also listed. The gate is rerun after each intake correction. The user may leave only
when `unattended_ready` is `true` or when the result is terminal `no-work`/`blocked`.

Result rules:

- `needs-user-input`: no manifest, claim, state creation, or worker dispatch;
- `blocked`: no claim; preserve any existing requirement evidence;
- `no-work`: no platform installation request, state creation, or claim;
- `ready`: `unattended_ready=true`; continue without another user wait;
- `resume-required`: if prerequisites are still met,
  `unattended_ready=true`; resume the exact persisted step.

A CSV `doing` row without recoverable local claim/requirement state is an orphaned
external state and returns `blocked`; the gate must not select or inspect the next
empty row.

Machine output includes the canonical `icp.entry-readiness-report.v1` and
`icp.entry-gate-decision.v1`. User-facing diagnostics use controlled reason text and
must not echo credentials, design tokens, arbitrary exception text, or absolute
private paths.

## 3. Requirement activation

After design analysis has produced verified feature positions and a verified
operation-plan digest, `icp_begin_requirement_v1.py` reruns the entry gate in the
same activation call. It may invoke
`prepare_single_requirement_with_entry_gate(...)` only when the fresh result is
`ready` and `unattended_ready=true`.

Activation acquires the state lock, recovers terminal and pending-claim state,
selects one row, freezes the selection manifest, publishes the entry-readiness and
package-selection documents, persists claim intent and execution scope, then CAS
claims the row as `doing`. At most one requirement is active.

## 4. Unattended execution and resume

Each side-effecting step records `started` progress before execution and publishes
one immutable receipt before advancing progress. Restart decisions come only from
the persisted active pointer, execution scope, progress, receipts, row observation,
and recovery journals. A restart must resume or replay the exact step and must not
select another row.

Next.js, iOS, and Android execution bindings lock the selection manifest,
entry-readiness document, package-selection document, and selected platform config.
A runtime JSON input may contain only values equal to the selected platform config.
Authorization and execution reverify those identities before effects.

Every successful runtime capture must come from a real browser, simulator, emulator,
or device. Design images are never used as visible application layers or reported as
actual runtime screenshots.

## 5. Terminal handling

Successful completion writes the claimed row to `done`; controlled failure writes it
to `error`. Writeback intent, observation, and terminal cleanup are restart-safe.
The active pointer and requirement progress are removed only after cleanup is
verified. Only then may the next requirement be selected.

## 6. Ownership boundary

Shared core owns task/design ingestion, canonical readiness, single-requirement
state, resume, checkpoint, writeback, cleanup, and common evidence contracts.
Platform packages own project shape, toolchain, dependencies, runtime selection,
operation plans, execution handlers, tests, gates, and real capture provenance.
`iff/**` is migration input and remains unchanged.
