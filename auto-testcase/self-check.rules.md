# Testcase Review Rules — Integration

Review the test plan, test code, and HLD by filling these tables. Every cell must quote actual text from the files. ID-only references are forbidden.

## Inputs

- `understand.md` — Acceptance Criteria, Affected Files
- `hld.md` — Module Interaction Flow, Module Boundaries, Function Signatures
- Test plan (from `testcase/` directory or inline in test file comments)
- Test code file(s) (`.test.ts` / `.test.tsx`)

## Part 1: Coverage Traceability

Read `hld.md` and the test code file(s).

**Table 1 — Flow → Test (one row per Flow in hld.md):**

Every Flow in the HLD Module Interaction Flow must have at least one corresponding `it()` block. Structural Flows (render-only, no user interaction) are EXEMPT.

| Flow | Flow Expected Output (quote from hld.md) | Test Case (quote `it()` name from test file) | Status |
|------|------------------------------------------|----------------------------------------------|--------|
| F1 | "selectedTopics unchanged, duplicateTag equals clicked tag" | `it('should not add duplicate topic')` | ✅ |
| F5 | "textarea displays typed text" | (no test covers F5) | ❌ gap |

**Completeness check (mandatory):**

```
Verification: hld.md contains N Flows (F1 through F?). This table has N rows. Match: YES/NO.
```

If NO — find the missing Flows and add rows. Do NOT proceed until counts match.

**Table 2 — Test → Flow/AC (one row per `it()` block in test file):**

Every `it()` block must trace back to at least one Flow and AC. A test without a corresponding Flow/AC is an orphan — it tests behavior that was never designed.

| Test Case (quote `it()` name from test file) | Flow | AC | Status |
|----------------------------------------------|------|----|--------|
| `it('should not add duplicate topic')` | F1 | AC-01 | ✅ |
| `it('should handle edge case')` | — | — | ❌ orphan |

**Completeness check (mandatory):**

```
Verification: Test file contains N it() blocks. This table has N rows. Match: YES/NO.
```

If NO — find the missing `it()` blocks and add rows.

**Table 3 — Plan = Code (count verification):**

```
Plan rows: N
it() blocks in test file: N
Match: YES/NO
Unmatched plan rows: [list]
Unmatched it() blocks: [list]
```

If NO — every plan row must have exactly one `it()`, and vice versa.

## Part 2: Mock Correctness

Read `hld.md` Module Boundaries and the test code file(s).

**Table 4 — Mock → Boundary (one row per mock/stub in test file):**

Every mock in the test must correspond to an External Boundary in the HLD Module Boundaries table. Mocking an Internal Dependency is forbidden — internal modules must be rendered/called for real.

| Mock Target (quote from test file) | HLD Classification (quote from hld.md) | Internal/External? | Status |
|-----------------------------------|-----------------------------------------|---------------------|--------|
| `vi.mock('~/utils/api')` | External Boundary: "fetch (network)" | External | ✅ |
| `vi.mock('./useOrderService')` | Internal Dependencies: "useOrderService" | Internal — should not mock | ❌ |

**Table 5 — Edge Contract Assertions (one row per connecting value across cross-module edges in hld.md Module Interaction Flow):**

For each Caller → Callee edge in the HLD Flow table, identify the connecting value (URL path, function arguments, API endpoint) that crosses the boundary. Every connecting value must be asserted in at least one test. A contract without assertion means the test cannot detect if the connection breaks.

| HLD Edge | Contract Type | Expected Value (quote from hld.md) | Test Assertion (quote from test file) | Status |
|----------|--------------|-------------------------------------|---------------------------------------|--------|
| OrderForm → API | URL path | "/api/orders" | `expect(mockApi).toHaveBeenCalledWith('/api/orders', ...)` | ✅ |
| OrderForm → API | payload | "{ title, content }" | (no assertion checks payload fields) | ❌ missing |

**Table 6 — Mock Args Completeness (one row per mocked API function that is called in tests):**

When an API function is mocked, every test that triggers it must assert BOTH the connecting value (e.g., URL path) AND the payload (e.g., request body). Asserting only `toHaveBeenCalled()` without checking arguments is insufficient.

| Mock Function (quote from test file) | Test Case | Connecting Value Asserted? (quote assertion) | Payload Asserted? (quote assertion) | Status |
|---------------------------------------|-----------|----------------------------------------------|-------------------------------------|--------|
| `mockApiFn` | `it('should submit order')` | `expect(mockApiFn.mock.calls[0][0]).toBe('/api/orders')` | `expect(calledOptions.body.title).toBe('...')` | ✅ |
| `mockApiFn` | `it('should handle error')` | (no connecting value assertion) | (no payload assertion) | ❌ incomplete |

## Part 3: Test Effectiveness

Read the test code and `hld.md`. This is the most important part — it checks whether tests actually verify what they claim to.

**Table 7 — Assertion Effectiveness (one row per `it()` block):**

For each test, verify: (1) the trigger matches the HLD Flow's immediate predecessor, (2) the assertion verifies the HLD Expected Output, (3) the assertion is an observable outcome (DOM/return value), not internal wiring.

| Test Case (quote `it()` name) | Trigger (quote from test) | Assertion (quote from test) | HLD Expected Output (quote from hld.md) | Effective? | Status |
|-------------------------------|---------------------------|-----------------------------|-----------------------------------------|------------|--------|
| `it('should show underline')` | `fireEvent.click(dupTopic)` | `expect(item).toHaveClass('underline')` | F2: "displayed with underline class" | yes — DOM result matches HLD | ✅ |
| `it('should reject dup')` | `fireEvent.click(dupTopic)` | `expect(mockFn).toHaveBeenCalled()` | F1: "selectedTopics unchanged" | no — asserts call, not state | ❌ |

**Effectiveness criteria (all must pass for ✅):**

1. **Trigger fidelity**: The trigger in the test must be the immediate cause of the asserted outcome as defined in the HLD Flow — not an earlier step in the chain. If the HLD defines A → B → C → D and the test asserts D, the trigger must be C.
2. **Assertion coverage**: The assertion must verify the HLD Flow's Expected Output — not a subset of it. If the Expected Output has 3 data values, the test should assert all 3.
3. **Observable outcome**: The assertion must use testing-library query and matcher APIs (`getByText`, `getByRole`, `toHaveTextContent`, `toBeVisible`, etc.) to verify user-visible results. Direct access to the render tree's internal structure (`.children`, `.props`, `.type`, `.parent`) constitutes internal state inspection and is forbidden, even when the accessed value appears to represent visible content.
4. **No Mock-as-Input-Output**: The test must NOT mock a value and then assert that the result equals that same mock value. The assertion must verify a real transformation or behavioral outcome driven by the mock input.

**Table 8 — Trigger Fidelity Detail (one row per `it()` that involves multi-step HLD Flows):**

Skip this table if all Flows are single-step. For multi-step Flows, verify the test's trigger is the immediate predecessor, not an earlier step.

| Test Case | HLD Flow Steps | Expected Trigger (immediate predecessor) | Actual Trigger (quote from test) | Status |
|-----------|---------------|------------------------------------------|----------------------------------|--------|
| `it('should save after validate')` | F1: input → validate → save → confirm | "validate passes" (step before save) | `fireEvent.click(submitBtn)` — triggers from input, skips validate | ❌ |

## Part 4: Test Code Quality

Read the test code file(s). These tables check whether the test code itself is well-written, independent of what it tests.

**Table 9 — Test Code Hygiene (one row per `it()` block):**

Each `it()` must satisfy all 4 hygiene criteria. Quote the offending code if any criterion fails.

| Test Case (quote `it()` name) | Logic-free? | No Dynamic Values? | Has Assertion? | Single Behavior? | Status |
|-------------------------------|-------------|-------------------|----------------|-------------------|--------|
| `it('should reject dup')` | yes | yes | yes (1 expect) | yes | ✅ |
| `it('should handle dates')` | no — `if (result)` | no — `new Date()` | yes | yes | ❌ |
| `it('should work')` | yes | yes | no — zero expect() | — | ❌ |

Criteria definitions:

- **Logic-free**: Test code must NOT contain `if`, `else`, `for`, `while`, `switch`, `? :` (ternary). Tests with logic can pass even when code is broken — the logic may skip the failing branch. Quote the offending statement if found.
- **No Dynamic Values**: Test code must NOT use non-deterministic values like `Date.now()`, `new Date()`, `Math.random()`, `crypto.randomUUID()`. These cause flaky tests. Controlled test fixtures (e.g., `new Date('2024-01-01')`) are acceptable.
- **Has Assertion**: Every `it()` must contain at least one `expect()` call. A test with no assertion is a "Secret Catcher" — it passes regardless of behavior.
- **Single Behavior**: Each `it()` should verify one behavior. Multiple unrelated assertions (e.g., checking both form validation AND API call in one test) indicate the test should be split. Related assertions verifying different aspects of the SAME outcome (e.g., checking both text content and CSS class after one action) are acceptable.

**Completeness check (mandatory):**

```
Verification: Test file contains N it() blocks. This table has N rows. Match: YES/NO.
```

**Table 10 — AAA Structure (one row per `it()` block):**

Each test should follow the Arrange-Act-Assert pattern with clear separation. Quote the relevant code sections.

| Test Case (quote `it()` name) | Arrange (quote setup from test) | Act (quote trigger from test) | Assert (quote expectation from test) | Clear Separation? | Status |
|-------------------------------|--------------------------------|-------------------------------|--------------------------------------|-------------------|--------|
| `it('should show underline')` | `render(<Post />); selectTopic('loans')` | `fireEvent.click(dupTopic)` | `expect(item).toHaveClass('underline')` | yes — setup, trigger, assertion clearly separated | ✅ |
| `it('should update list')` | (setup and action interleaved: renders, clicks, renders again, clicks again, then asserts) | (mixed with arrange) | `expect(list).toHaveLength(2)` | no — arrange and act interleaved | ❌ |

Criteria:

- **Arrange**: Setup code (render, create fixtures, configure mocks) is grouped at the beginning.
- **Act**: A single trigger action (click, call, submit) happens in one place — not scattered throughout the test.
- **Assert**: All assertions come after the action — not interleaved with setup or additional actions.
- **Clear Separation**: The three phases are visually distinct. Tests that mix setup, action, and assertion across multiple interleaved steps are unclear about what is being tested.

**Table 11 — Mutation Resilience (one row per `it()` block, focusing on critical logic paths):**

For each test, identify the core assertion and ask: if a key operator or value in the production code were changed (mutated), would this test catch it? This checks whether the test provides real safety or is just coverage padding.

| Test Case (quote `it()` name) | Core Assertion (quote from test) | Hypothetical Mutation | Would Test Catch It? | Status |
|-------------------------------|--------------------------------|----------------------|---------------------|--------|
| `it('should reject dup')` | `expect(topics).toHaveLength(1)` | Change `includes(tag)` to `!includes(tag)` in production code | yes — duplicate would be added, length would be 2 | ✅ |
| `it('should show list')` | `expect(list).toBeVisible()` | Change API response from success to error | no — test mocks success, never tests that the visibility depends on success | ❌ |
| `it('should format price')` | `expect(result).toBe('$10.00')` | Change `toFixed(2)` to `toFixed(1)` in production code | yes — result would be '$10.0', assertion would fail | ✅ |

How to evaluate:

1. **Identify the core logic** the test claims to verify (from the HLD Flow or AC).
2. **Propose one realistic mutation** — a small change a developer might accidentally make (flip a condition, change an operator, remove a line, swap arguments).
3. **Trace through**: with this mutation, would the test's assertion still pass or would it fail?
4. If the test would still **pass** despite the mutation → the test is weak (❌). If the test would **fail** → the test provides real safety (✅).

Common mutations to consider:
- Flip condition: `===` → `!==`, `>` → `>=`, `&&` → `||`
- Remove line: delete the key operation (e.g., remove the `push()` call)
- Swap arguments: reverse parameter order
- Change value: `null` → `undefined`, `0` → `1`, `true` → `false`

## Part 5: HLD Contract Fidelity

Read `hld.md` (Interfaces, Function Signatures) and the test code file(s). These tables check whether the test code faithfully uses the contracts defined in the HLD.

**Table 12 — Signature Match (one row per application function called in test code):**

Every call to an application function (imported from source files, NOT test framework utilities like `vi.fn`, `render`, `screen.*`) must match the HLD-defined signature — name, parameter types, and return type.

| Function Call (quote from test file) | HLD Signature (quote from hld.md) | Match? | Status |
|--------------------------------------|-----------------------------------|--------|--------|
| `handleTopicSelect('loans')` | "handleTopicSelect: (tag: string) => void" | yes — string arg matches string param | ✅ |
| `handleTopicSelect(123)` | "handleTopicSelect: (tag: string) => void" | no — number vs string | ❌ SIG_DRIFT |

**Table 13 — Type Consistency (one row per mock return value and test fixture that represents an HLD-defined type):**

Every type used in mock return values and test fixtures must match the HLD-defined interface. A mock that returns a shape different from the HLD interface makes tests pass against a phantom contract.

| Mock/Fixture (quote from test file) | HLD Interface (quote from hld.md) | Match? | Status |
|-------------------------------------|-----------------------------------|--------|--------|
| `mockUseTopic.mockReturnValue({ selectedTopics: [], duplicateTag: null })` | "useTopic returns { selectedTopics: string[], duplicateTag: string \| null, ... }" | yes — shape matches | ✅ |
| `mockApi.mockResolvedValue({ data: items })` | "ApiResponse<T> = { code: number, data: T, message: string }" | no — missing code and message fields | ❌ TYPE_DRIFT |

**Table 14 — Import Path Alignment (one row per application import in test file):**

Every import from application source code must point to a file listed in understand.md → Affected Files or a shared/common module. Imports from unlisted files indicate scope creep in the test.

| Import (quote from test file) | In Affected Files or shared module? | Status |
|-------------------------------|-------------------------------------|--------|
| `import { useTopic } from '@/app/(protected)/post/hooks'` | yes — "src/app/(protected)/post/hooks.ts" in Affected Files | ✅ |
| `import { formatDate } from '@/utils/date'` | yes — shared utility module | ✅ |
| `import { AdminPanel } from '@/app/admin/panel'` | no — not in Affected Files, not a shared module | ❌ IMPORT_PHANTOM |

**Table 15 — No Implementation in Test (one row per test file):**

Test files must contain only test code (describe/it blocks, setup, assertions, mocks). Any business logic, utility functions, data transformations, or component implementations in test files indicate code that belongs in source files.

| Test File | Implementation Code Found? (quote if found) | Status |
|-----------|---------------------------------------------|--------|
| `interactions.test.tsx` | no — only describe/it/expect/mock | ✅ |
| `api.test.ts` | yes — `function formatResponse(data) { return { ...data, formatted: true } }` (lines 15-17) — this is a data transformer that belongs in source | ❌ IMPL_IN_TEST |

## Summary

```
| Category | Total | Pass | Fail | Exempt |
|----------|-------|------|------|--------|
| Flow → Test | X | X | X | X |
| Test → Flow/AC | X | X | X | X |
| Plan = Code | match/mismatch | | | |
| Mock → Boundary | X | X | X | X |
| Edge Contract Assertions | X | X | X | X |
| Mock Args Completeness | X | X | X | X |
| Assertion Effectiveness | X | X | X | X |
| Trigger Fidelity Detail | X | X | X | X |
| Test Code Hygiene | X | X | X | X |
| AAA Structure | X | X | X | X |
| Mutation Resilience | X | X | X | X |
| Signature Match | X | X | X | X |
| Type Consistency | X | X | X | X |
| Import Path Alignment | X | X | X | X |
| No Implementation in Test | X | X | X | X |

Verdict: ALL PASS / X issues found
```
