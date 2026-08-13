# ICP Self-Check v1

Date: 2026-07-18

Final status: **PASS**

## Parameters

| Parameter | Value |
|---|---|
| Rules | `references/runtime-contract-v1.md` |
| Scope | `SKILL.md`, entry/readiness/activation/task-source/state/orchestrator modules, seven platform packages and preflights, execution bindings, registry, and self-tests |
| Report | `references/icp-self-check-v1.md` |
| Protected scope | `iff/**` must remain unchanged |

## Requirement evidence

| Requirement | Evidence | Status |
|---|---|---|
| Select platform before dependency inspection | `icp_entry_v1.py` resolves one package from the normalized platform/profile selection, then calls that package's `inspect_entry_requirements(project_root)` API. | PASS |
| Never request unrelated platform dependencies | The shared entry contains no `npm`, `flutter`, `xcode`, or `adb` branches. Those checks live under `scripts/platforms/`. | PASS |
| Finish user-attended intake before unattended work | Entry readiness emits `needs-user-input` until the selected package's project root, project materials, toolchain, dependencies, runtime configuration, and runtime target are complete. `unattended_ready` is false in that state. | PASS |
| Report all currently detectable omissions together | Platform inspectors aggregate missing and deferred checks instead of returning at the first absent configuration, tool, dependency, project marker, or runtime target. | PASS |
| Prove the task source can support atomic state change before claiming | `csv_task_source.probe_write_readiness()` performs a same-directory write, fsync, replace, verify, cleanup, and directory fsync without changing the task source. | PASS |
| Do not claim on incomplete entry | `icp_begin_requirement_v1.py` re-runs entry readiness immediately before activation and calls the claim/prepare API only when status is `ready` and `unattended_ready` is true. | PASS |
| No work means no state or claim | `no-work` returns without platform install requests, state creation, or task claim. | PASS |
| Resume the exact active requirement | An active pointer takes precedence over selecting a new row; entry returns `resume-required` with the existing state, progress, receipts, and identity evidence. | PASS |
| Missing resume prerequisites require the user | An active requirement whose prerequisite check returns `needs-user-input` remains non-unattended. | PASS |
| Never bypass an orphan `doing` row | A `doing` row without recoverable local state returns `blocked` with `orphan_doing_without_state`; no later row is selected. | PASS |
| Bind execution to the approved entry | Platform execution bindings verify selection, entry-readiness, package-selection, platform-config, operation-plan, and operation-input identities before effects. Runtime overrides that differ from approved configuration are rejected. | PASS |
| Clean state only after one terminal requirement | The runtime contract requires terminal evidence and task-source finalization before clearing the active state; the next requirement starts only after cleanup. | PASS |
| Keep shared design/task logic separate from platform logic | Shared entry/readiness/task/state orchestration is platform-neutral; platform tools, project markers, dependencies, runtime targets, plans, and effects are package-owned. | PASS |
| Preserve IFF | `git diff --exit-code -- iff` exits successfully. | PASS |

## Findings and fixes

| Initial finding | Resolution | Status |
|---|---|---|
| Some platform preflights returned after a missing config and could not list later missing items. | Changed preflights to aggregate platform configuration, project materials, tools, dependencies, runtime target, and deferred probes in one result. | FIXED |
| Entry did not use the canonical readiness decision. | Integrated `aggregate_readiness()` and `decide_entry()`; entry now emits one canonical report and gate decision. | FIXED |
| There was no production bridge between readiness and the atomic claim API. | Added `icp_begin_requirement_v1.py`, with a fresh readiness check immediately before activation. | FIXED |
| `no-work` could perform unnecessary state preparation. | Made `no-work` terminal before state creation or claim and removed platform installation requests from its result. | FIXED |
| CSV writability did not prove same-directory atomic replacement. | Added a non-destructive atomic write-readiness probe with byte and directory-preservation tests. | FIXED |
| Shared entry contained Vue/Flutter-specific checks. | Moved every selected-platform check behind the platform package interface. | FIXED |
| Package descriptors did not expose the complete entry requirement contract. | All seven packages now declare the six common requirement categories and implement package-owned inspection. | FIXED |
| Runtime execution could differ from the configuration approved at entry. | Bound execution to canonical platform-config evidence and reject mismatched runtime projections. | FIXED |
| An active pointer without a pending claim could be ignored. | Active state now wins independently of pending-claim presence. | FIXED |
| A resume prerequisite failure could be reported as unattended. | Propagate inner `needs-user-input` and `blocked` statuses; only valid resume state is unattended. | FIXED |
| An orphan `doing` row could allow a second row to be selected. | Detect and block orphan active rows before candidate selection. | FIXED |
| The orchestrator checked fields on the seam wrapper instead of nested `preparation_ack`. | Validate the nested acknowledgement, allowing successful claim to activate state correctly. | FIXED |
| Raw exception/path text could escape through entry output. | Replaced arbitrary exception strings with controlled public errors and a generic fatal message. | FIXED |
| The public atomic claim API accepted any 64-character operation-plan digest even though the CLI required lowercase SHA-256 hex. | Enforced lowercase hexadecimal SHA-256 syntax at the side-effect boundary and added a pre-effect regression test. | FIXED |
| Historical design notes could be mistaken for the current contract. | Added `runtime-contract-v1.md` as the active contract and labelled historical material in `SKILL.md`. | FIXED |

## Final verification

| Verification | Result |
|---|---|
| All 40 `selftest_*.py` files, executed serially | PASS |
| Ready entry -> atomic single-row `doing` claim -> active state -> exact `resume-required` re-entry | PASS |
| Selected-platform complete missing-list tests for Next.js, iOS, and Android | PASS |
| Runtime configuration mismatch rejection for Next.js, iOS, Android, and Vue | PASS |
| Vue, Next.js, iOS, and Android controlled execution parity tests | PASS |
| Seven live platform package resolutions and package-aware activation gate | PASS |
| Skill Creator `quick_validate.py icp` | PASS (`Skill is valid!`) |
| `git diff --exit-code -- iff` | PASS |
| Shared entry searches for `npm`, `flutter`, `xcode`, `adb`, and `str(exc)` | PASS (no matches) |
| `__pycache__` and `node_modules` directories under `icp/` | PASS (none) |

The self-test suite must run serially: integrity tests intentionally mutate and restore isolated frozen artifacts, so concurrent self-test processes can race with unrelated capsule verification.
