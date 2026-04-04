# Write Test Cases & Review (Step 2)

## 2a. Determine test scope

**Unit tests** - based on the confirmed understanding, draft a test plan:
- Which functions or modules to test
- What scenarios (happy path, edge cases, errors)
- Expected behavior for each case

**STOP and present the test plan to the user.** Wait for the user to confirm it, add cases, adjust scope, or remove cases.

**Integration or E2E tests** - after the unit test plan is confirmed, ask the user:

> Do you need integration or E2E tests?

- If no, proceed to 2b.
- If yes, the user specifies what to test. **STOP and confirm** the user's requested test cases. Do not proceed to 2b until the user confirms the final list.

## 2b. Load rules & write tests

Once all test types and scope are confirmed, use the `my-subagent` skill to load the relevant test rules. Do not call `spawn_agent` directly.

> Based on the confirmed test types, select ONLY the matching rule files from `/Users/Woo/.agents/skills/auto-testcase/`:
> - Always: `general.md`
> - Unit tests: `unit.md`
> - Integration tests: `integration.md`
> - E2E tests: `e2e.md`
>
> From the selected files, extract and return ONLY the rule sections relevant to this task. Do not return entire files.
>
> **Task context:**
> - Summary: [paste the confirmed understanding from Step 1]
> - Files to test: [list of files]
> - Test types: [only the confirmed types]

Write test code based on the confirmed plan and returned rules.

## 2c. Review & run red tests

**STOP and ask the user:**

> Test code is complete. Would you like to review it before I run the red phase?

- If yes, wait for feedback, apply changes, then ask again whether to proceed.
- If no, proceed.

Run the test suite to verify that the tests fail as expected in the red phase. For new features, all new tests MUST fail. If they pass without implementation, the tests are wrong. For bug fixes, the new bug-reproducing tests MUST fail, while existing tests may pass.
