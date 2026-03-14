# Audit: Requirements Analysis + HLD Design

Audit the [Requirements Analysis] and [HLD Design] against the [User's Original Request] and [Architectural Rules]. Report every issue found.

## Checks

### Requirements

| Check | Pass Criteria | Fail Category |
|-------|---------------|---------------|
| AC Completeness | Every distinct behavior/constraint in user request has a corresponding AC | `AC_MISSING` — behavior not covered; `AC_OVERCLAIM` — AC describes behavior not in user request |
| AC Precision | Each AC specifies an observable, testable outcome | `AC_VAGUE` — imprecise language without observable outcome; `AC_UNTESTABLE` — describes internal state, not behavior |
| Affected Files | Every listed file is justified by an AC; every file implied by the analysis is listed | `FILE_PHANTOM` — listed but unjustified; `FILE_MISSING` — implied but not listed |
| Implicit Requirements | Error handling, loading states, edge cases implied by user request are captured | `IMPLICIT_MISSING` — reasonable implicit requirement not covered by any AC |

### HLD Design

| Check | Pass Criteria | Fail Category |
|-------|---------------|---------------|
| AC ↔ HLD Mapping | Every AC has at least one HLD element; every HLD element traces to an AC | `HLD_GAP` — AC has no HLD element; `HLD_ORPHAN` — HLD element traces to no AC |
| Contract Purity | HLD contains only types, signatures, and boundaries — no logic, loops, conditionals, JSX, or function bodies | `IMPL_LEAK` — implementation detail in HLD |
| Flow Continuity | Every flow step has a causal predecessor and successor; no skipped intermediate states | `FLOW_SKIP` — step jumps over intermediate state; `FLOW_ORPHAN` — step not traceable to any AC |
| Error Path Coverage | Every flow with a success path also defines an error path (when the AC implies both) | `FLOW_MISSING_PATH` — success path exists but error path is absent (or vice versa) |
| Signature Consistency | Caller argument types match callee parameter types across all module interactions | `SIG_MISMATCH` — type mismatch between caller and callee; `SIG_INCOMPLETE` — missing return type or parameter type |
| Boundary Correctness | Module dependencies are correctly classified as internal or external, and all dependencies are declared | `BOUNDARY_MISCLASS` — wrong classification; `BOUNDARY_MISSING` — undeclared dependency |
| Scope Discipline | HLD does not introduce modules, flows, or features beyond what the ACs define | `SCOPE_CREEP` — functionality not covered by any AC |

### Cross-Cutting

| Check | Pass Criteria | Fail Category |
|-------|---------------|---------------|
| Traceability Chain | Complete chain exists: User Request → AC → HLD Module → HLD Flow | `CHAIN_BREAK` — a link in the chain is missing |
| Architectural Compliance | All interfaces, signatures, and boundaries comply with [Architectural Rules] | `RULE_VIOLATION` — conflicts with a specific architectural rule (cite the rule) |

## Output Format

If no issues: `STATUS: 100% COMPLIANT`

Otherwise, a single table — one row per issue, every row must reference a specific artifact ID (AC-XX, F-XX, module name):

| ID | Location | Severity | Category | Description | Required Fix |
|:---|:---|:---|:---|:---|:---|
| 01 | AC-XX | BLOCKER | AC_MISSING | ... | ... |

Severity: **BLOCKER** (must fix before proceeding) | **WARN** (should fix) | **INFO** (suggestion)

---

## Inputs

### [User's Original Request]
<!-- Include the user's chat message AND the full content of any referenced spec/requirement files (PRDs, feature specs, etc.) that the understand subagent read to derive ACs. Without the spec content, AC traceability checks will produce false positives. -->
<USER_REQUEST>
</USER_REQUEST>

### [Requirements Analysis]
<REQUIREMENTS>
</REQUIREMENTS>

### [HLD Design]
<HLD>
</HLD>

### [Architectural Rules]
<RULES>
</RULES>
