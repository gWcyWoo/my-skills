---
name: write-tests
description: Determine test scope, load test rules, write test code, and run red tests. Reusable test-writing step for any workflow.
---

# Write Test Cases & Review

## 1. Determine test scope

**Unit tests** — based on the requirement understanding, draft a test plan:
- Which functions/modules to test
- What scenarios (happy path, edge cases, errors)
- Expected behavior for each case

**STOP and present the test plan to the user.** Wait for user to confirm, add, adjust, or remove cases.

**Integration / E2E tests** — after unit test plan is confirmed, ask the user:

> Do you need integration or E2E tests?

- If no → proceed to step 2.
- If yes → user specifies what to test. **STOP and confirm** the user's test cases: are these complete? Any additions or removals? Do NOT proceed to step 2 until user confirms the final list.

## 2. Load rules & write tests

Once all test types and scope are confirmed, dispatch a subagent to load relevant test rules:

> Based on the confirmed test types, select ONLY the matching rule files from `~/.claude/skills/auto-testcase/`:
> - Always → `general.md`
> - Unit tests → `unit.md`
> - Integration tests → `integration.md`
> - E2E tests → `e2e.md`
>
> From the selected files, extract and return ONLY the rule sections relevant to this task. Do not return entire files.
>
> **Task context:**
> - Summary: [paste the confirmed understanding]
> - Files to test: [list of files]
> - Test types: [only the confirmed types]

Write test code based on the confirmed plan and returned rules.

## 3. Review & run red tests

**STOP and ask the user:**

> Test code complete. Would you like to review before proceeding?

- If yes → wait for feedback, apply changes.
- If no → proceed.

Run the test suite to verify tests fail as expected (red phase). For new features, all new tests MUST fail — if they pass without implementation, the tests are wrong. For bug fixes, the new bug-reproducing tests MUST fail while existing tests may pass.
