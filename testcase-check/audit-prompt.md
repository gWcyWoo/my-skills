# Audit: Test Cases

Audit test code against HLD contracts and test design rules. Tests that pass this audit become the locked specification — implementation must conform to them, not the other way around.

Report every issue found.

## Checks

### HLD Contract Fidelity (test code vs hld.md)

| Check | Pass Criteria | Fail Category |
|-------|---------------|---------------|
| Signature Match | Every call to an application function (imported from source files, not test framework utilities like `vi.fn`, `render`, `screen.*`) matches the HLD-defined signature (name, parameters, return type) | `SIG_DRIFT` — test calls an application function with different name, parameter types, or return type than HLD defines |
| Type Consistency | Every type used in test assertions and mock return values matches HLD-defined interfaces | `TYPE_DRIFT` — test uses a type shape that differs from HLD interface definition |
| Import Path Alignment | Every import path in test code points to a file listed in understand → Affected Files or a shared module | `IMPORT_PHANTOM` — test imports from a path not justified by HLD or understand |

### Assertion Quality (test code vs test design rules)

| Check | Pass Criteria | Fail Category |
|-------|---------------|---------------|
| No Mock-as-Output | No test mocks a value and then asserts the result equals that same mock value | `HOLLOW_ASSERT` — test asserts the mock value itself, proving nothing about real behavior |
| Behavioral Assertion | Integration tests assert observable outcomes (rendered output, return values, API responses), not internal state or props. Unit tests assert return values or state transformations. Neither type uses `toHaveBeenCalled()` as the sole assertion without a corresponding outcome assertion | `INTERNAL_ASSERT` — test asserts props, internal state, or implementation details; or uses `toHaveBeenCalled()` as the only assertion |
| Complete Mock Call Assertion | When an API function is mocked, tests assert both the connecting value (URL/path) and the payload | `PARTIAL_MOCK_ASSERT` — test asserts only `toHaveBeenCalled()` or only the payload, missing the connecting value |

### Mock Boundary Correctness (test code vs HLD module boundaries)

| Check | Pass Criteria | Fail Category |
|-------|---------------|---------------|
| External Boundary Only | For integration tests: mocks target only the outermost external boundary (network/DB/API), not internal modules. For unit tests: the one allowed mock may target an internal dependency | `INTERNAL_MOCK` — integration test mocks an internal module that should run for real |
| Mock Count | Integration tests have at most 1 mock; unit tests have at most 1 mock | `OVER_MOCK` — test uses more mocks than allowed by the iron rule |

### AC Coverage (test code vs understand.md)

| Check | Pass Criteria | Fail Category |
|-------|---------------|---------------|
| AC Completeness | Every AC ID from understand.md appears in at least one test case's traceability mapping, unless the test plan explicitly marks it as covered by a different test type (e.g., "unit test scope" or "covered by integration") | `AC_UNCOVERED` — an AC has no corresponding test case and is not delegated to another test type |
| No Orphan Tests | Every test case traces to an AC ID | `TEST_ORPHAN` — test case exists but traces to no AC |

### Implementation Leak (test code only)

| Check | Pass Criteria | Fail Category |
|-------|---------------|---------------|
| No Implementation Code | Test files contain only test code (describe/it blocks, setup, assertions, mocks). No business logic, utility functions, or component implementations | `IMPL_IN_TEST` — test file contains implementation code that belongs in source files |

## Output Format

If no issues: `STATUS: 100% COMPLIANT`

Otherwise, a single table — one row per issue, every row must reference a specific artifact (test file, it() block, AC-XX, HLD signature):

| ID | Location | Severity | Category | Description | Required Fix |
|:---|:---|:---|:---|:---|:---|
| 01 | test-file.ts:it("...") | BLOCKER | SIG_DRIFT | ... | ... |

Severity: **BLOCKER** (must fix before proceeding) | **WARN** (should fix) | **INFO** (suggestion)

---

## Inputs

### [HLD Design]
<HLD>
</HLD>

### [Requirements Analysis]
<UNDERSTAND>
</UNDERSTAND>

### [Test Plan]
<TEST_PLAN>
</TEST_PLAN>

### [Test Code Files]
<TEST_CODE>
</TEST_CODE>
