# Audit: Understand + HLD

Audit two documents independently:
1. **understand.md** — check if the Requirements Analysis correctly and completely captures the user's original request
2. **hld.md** — check if the HLD design follows coding standards and correctly maps to every AC in understand.md

Report every issue found.

## Checks

### Requirements Analysis (understand.md vs requirement.md)

| Check | Pass Criteria | Fail Category |
|-------|---------------|---------------|
| AC Completeness | Every distinct behavior/constraint in user request has a corresponding AC | `AC_MISSING` — behavior not covered; `AC_OVERCLAIM` — AC describes behavior not in user request |
| AC Precision | Each AC specifies an observable, testable outcome | `AC_VAGUE` — imprecise language without observable outcome; `AC_UNTESTABLE` — describes internal state, not behavior |
| Affected Files | Every listed file is justified by an AC; every file implied by the analysis is listed | `FILE_PHANTOM` — listed but unjustified; `FILE_MISSING` — implied but not listed |
| Implicit Requirements | Error handling, loading states, edge cases implied by user request are captured | `IMPLICIT_MISSING` — reasonable implicit requirement not covered by any AC |
| AC Cross-Consistency | All ACs that reference the same field, state, or behavior are consistent with each other (no contradictions in values, types, or allowed states) | `AC_CONFLICT` — two or more ACs define contradictory values, types, or behaviors for the same element |

### HLD Design (hld.md vs coding standards)

| Check | Pass Criteria | Fail Category |
|-------|---------------|---------------|
| Contract Purity | HLD contains only types, signatures, and boundaries — no logic, loops, conditionals, JSX, or function bodies | `IMPL_LEAK` — implementation detail in HLD |
| Flow Continuity | Every flow step has a causal predecessor and successor; no skipped intermediate states | `FLOW_SKIP` — step jumps over intermediate state |
| Error Path Coverage | Every flow with a success path also defines an error path (when the AC implies both) | `FLOW_MISSING_PATH` — success path exists but error path is absent (or vice versa) |
| Signature Consistency | Caller argument types match callee parameter types across all module interactions | `SIG_MISMATCH` — type mismatch between caller and callee; `SIG_INCOMPLETE` — missing return type or parameter type |
| Boundary Correctness | Module dependencies are correctly classified as internal or external, and all dependencies are declared | `BOUNDARY_MISCLASS` — wrong classification; `BOUNDARY_MISSING` — undeclared dependency |
| Data Origin Traceability | Every field in a Flow's Expected Output can be traced to an upstream Flow's output or an external input | `DATA_ORIGIN_MISSING` — a field appears in a Flow output but no upstream Flow or external input produces it |
| Architectural Compliance | All interfaces, signatures, and boundaries comply with [Coding Standards] | `RULE_VIOLATION` — conflicts with a specific coding standard (cite the rule) |

### Cross-File Consistency (understand.md ↔ hld.md)

| Check | Pass Criteria | Fail Category |
|-------|---------------|---------------|
| AC ↔ HLD Mapping | Every AC has at least one HLD element; every HLD element traces to an AC | `HLD_GAP` — AC has no HLD element; `HLD_ORPHAN` — HLD element traces to no AC |
| Scope Discipline | HLD does not introduce modules, flows, or features beyond what the ACs define | `SCOPE_CREEP` — functionality not covered by any AC |

## Output Format

If no issues: `STATUS: 100% COMPLIANT`

Otherwise, a single table — one row per issue, every row must reference a specific artifact (AC-XX, module name, flow step, signature):

| ID | Location | Severity | Category | Description | Required Fix |
|:---|:---|:---|:---|:---|:---|
| 01 | AC-XX | BLOCKER | AC_MISSING | ... | ... |

Severity: **BLOCKER** (must fix before proceeding) | **WARN** (should fix) | **INFO** (suggestion)

---

## Inputs

### [User's Original Request]
<USER_REQUEST>
</USER_REQUEST>

### [Requirements Analysis]
<UNDERSTAND>
</UNDERSTAND>

### [HLD Design]
<HLD>
</HLD>

### [Coding Standards]
<RULES>
</RULES>
