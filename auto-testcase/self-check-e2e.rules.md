# Testcase Review Rules — E2E

Review the e2e test plan, test code, and HLD by filling these tables. Every cell must quote actual text from the files. ID-only references are forbidden.

## Inputs

- `understand.md` — Acceptance Criteria, Affected Files
- `hld.md` — Module Interaction Flow, Module Boundaries, Function Signatures
- Test plan (from `testcase/` directory or inline in test file comments)
- Test code file(s) (`.test.ts` / `.spec.ts`)

## Part 1: Coverage Traceability

Read `hld.md` and the test code file(s).

**Table 1 — Flow → Test (one row per Flow in hld.md):**

Every user-facing Flow in the HLD must have at least one corresponding test block. Internal-only Flows (no UI impact) are EXEMPT.

| Flow | Flow Expected Output (quote from hld.md) | Test Case (quote test name from test file) | Status |
|------|------------------------------------------|---------------------------------------------|--------|
| F1 | "image preview displayed after upload" | `test('uploaded image shows preview')` | ✅ |
| F5 | "state reset on form clear" | (no test covers F5) | ❌ gap |

**Completeness check (mandatory):**

```
Verification: hld.md contains N user-facing Flows. This table has N rows. Match: YES/NO.
```

**Table 2 — Test → Flow/AC (one row per test block in test file):**

Every test must trace back to at least one Flow and AC. A test without a corresponding Flow/AC is an orphan.

| Test Case (quote test name from test file) | Flow | AC | Status |
|---------------------------------------------|------|----|--------|
| `test('uploaded image shows preview')` | F1 | AC-01 | ✅ |
| `test('handles edge case')` | — | — | ❌ orphan |

**Completeness check (mandatory):**

```
Verification: Test file contains N test blocks. This table has N rows. Match: YES/NO.
```

**Table 3 — Plan = Code (count verification):**

```
Plan rows: N
test() blocks in test file: N
Match: YES/NO
Unmatched plan rows: [list]
Unmatched test() blocks: [list]
```

## Part 2: Zero Mocking (P0 — Blocker)

E2E tests MUST run against the real application stack (Frontend + Backend + DB). Any form of request interception, mocking, or stubbing means the test is not truly end-to-end.

**Table 4 — Mock Scan (one row per pattern, scan ALL test files):**

| Pattern | Found? (quote if found) | Status |
|---------|------------------------|--------|
| `vi.mock` / `jest.mock` | (quote if found) | ✅/❌ |
| `vi.fn` / `jest.fn` used as API stub | (quote if found) | ✅/❌ |
| `page.route` / request interception | (quote if found) | ✅/❌ |
| `mockResolvedValue` / `mockReturnValue` on API functions | (quote if found) | ✅/❌ |
| Any other request interception mechanism | (quote if found) | ✅/❌ |

**Rule: ANY match is a P0 blocker.** The only exception is mocking external 3rd-party services (payment gateways, SMS providers) that cannot run in test environments. If an exception is claimed, the test must justify it in a comment.

**Table 5 — Real Backend Verification (one row per test that involves server interaction):**

For each test that triggers a server request (form submit, API call, data fetch), verify that the test interacts with a real backend — not an intercepted/mocked response.

| Test Case | Server Interaction | Real Backend? (evidence from test code) | Status |
|-----------|-------------------|----------------------------------------|--------|
| `test('upload image')` | POST to upload endpoint | no — `page.route('/api/upload', ...)` intercepts request | ❌ |
| `test('load topic list')` | GET topics from API | yes — no interception, renders real API data | ✅ |

## Part 3: Test Effectiveness

**Table 6 — Assertion on Final State (one row per test):**

E2E tests must assert the **final stable state**, not a transient intermediate state. If a user action triggers an async operation (upload, API call, navigation), the assertion must wait for the operation to complete and verify the result.

| Test Case | User Action | Async Operation? | Asserts Final State? (quote assertion) | Status |
|-----------|------------|-------------------|----------------------------------------|--------|
| `test('upload image')` | select file | yes — upload to server | no — asserts preview visible immediately, does not wait for upload completion | ❌ transient |
| `test('delete image')` | click delete | no — local state only | yes — `expect(preview).not.toBeVisible()` | ✅ |

**Transient state anti-pattern:** If a test asserts an element is visible right after an action but before an async operation completes, the test may pass even when the async operation fails (e.g., upload 404 → preview removed, but test already passed). The assertion must verify the state AFTER the async operation resolves.

**Table 7 — Mutation Resilience (one row per test, focusing on critical paths):**

| Test Case | Core Assertion (quote) | Hypothetical Mutation | Would Test Catch It? | Status |
|-----------|----------------------|----------------------|---------------------|--------|
| `test('upload')` | `expect(preview).toBeVisible()` | Remove the upload handler entirely | no — preview is from local base64, not upload result | ❌ |
| `test('delete')` | `expect(preview).not.toBeVisible()` | Remove delete handler | yes — preview would remain visible | ✅ |

## Part 4: Test Code Quality

**Table 8 — Test Code Hygiene (one row per test block):**

| Test Case | Logic-free? | No Dynamic Values? | Has Assertion? | Single Journey? | Status |
|-----------|-------------|-------------------|----------------|-----------------|--------|
| `test('upload image')` | yes | yes | yes | yes | ✅ |
| `test('full flow')` | no — `if (uploaded)` | yes | yes | no — tests upload + delete + reupload | ❌ |

Criteria:
- **Logic-free**: No `if`, `for`, `while`, `switch`, `? :` in test code
- **No Dynamic Values**: No `Date.now()`, `Math.random()`, etc.
- **Has Assertion**: At least one `expect()` per test
- **Single Journey**: Each test verifies one user journey or meaningful sub-journey

**Completeness check (mandatory):**

```
Verification: Test file contains N test blocks. This table has N rows. Match: YES/NO.
```

## Part 5: HLD Contract Fidelity

**Table 9 — Navigation Path Alignment (one row per `page.goto()` or route navigation in test file):**

Every navigation in the test must target a page related to the Affected Files or a valid application route.

| URL (quote from test) | In Affected Files or valid route? | Status |
|----------------------|----------------------------------|--------|
| `page.goto('/post')` | yes — post page in Affected Files | ✅ |
| `page.goto('/admin/settings')` | no — not in Affected Files | ❌ scope creep |

**Table 10 — No Implementation in Test (one row per test file):**

Test files must contain only test code. Any business logic, data transformations, or component implementations belong in source files.

| Test File | Implementation Code Found? (quote if found) | Status |
|-----------|---------------------------------------------|--------|
| `upload.spec.ts` | no — only test setup and assertions | ✅ |

## Summary

```
| Category | Severity | Total | Pass | Fail | Exempt |
|----------|----------|-------|------|------|--------|
| Flow → Test | — | X | X | X | X |
| Test → Flow/AC | — | X | X | X | X |
| Plan = Code | — | match/mismatch | | | |
| Mock Scan | P0 | X | X | X | X |
| Real Backend Verification | P0 | X | X | X | X |
| Assertion on Final State | P0 | X | X | X | X |
| Mutation Resilience | P1 | X | X | X | X |
| Test Code Hygiene | P1/P2 | X | X | X | X |
| Navigation Path Alignment | P1 | X | X | X | X |
| No Implementation in Test | P1 | X | X | X | X |

Verdict: ALL PASS / X P0 blockers, X P1 issues, X P2 suggestions
```
