# Lint, Test & Done (Step 4)

## 4a. Lint

Run the project's lint command. Fix all errors. If the same error persists after **3 consecutive fix attempts**, trigger **Stuck Escalation** (below).

## 4b. Unit/Integration Tests

Run the project's relevant unit and integration test command or commands.

If tests fail:
- **Your implementation has a bug**: fix the implementation and re-run the tests.
- **A test case needs modification**: **STOP and ask the user** before changing any test. Explain what the test expects, what the code does, and let the user decide.

**FORBIDDEN**: Modifying test cases without user approval.

If the same issue occurs **3 consecutive times**, trigger **Stuck Escalation** (below).

## 4c. E2E Tests (if applicable)

If E2E test cases were written in Step 2, **STOP and ask the user**:

> Unit/integration tests passed. Run E2E tests now?

- If no, skip to 4d.
- If yes, run the E2E tests. If they fail, apply the same rules as 4b.

If no E2E test cases were written, skip to 4d.

## Stuck Escalation

When the same error persists after 3 consecutive fix attempts:

1. **Re-analyze** - stop fixing symptoms. Re-read the failing code and error output from scratch. Identify the root cause.

2. **Research** - search external technical sources such as GitHub issues, Stack Overflow, and technical blogs for the specific error or pattern.

3. **Try a new approach** - implement a fundamentally different solution. Explain to the user what you found and why you are changing strategy.

If the new approach also fails after 3 consecutive attempts, **STOP and present the situation to the user** with all findings and attempted approaches.

## 4d. Done

Report what was changed:
- Files modified or created
- Tests run, passed, failed, or skipped
- Lint status
