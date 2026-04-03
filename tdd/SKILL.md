---
name: tdd
description: Use when implementing a small requirement or bug fix in a JavaScript or TypeScript repository and you want a user-in-the-loop TDD workflow in the main session.
---

# TDD

Default workflow for small requirements and bug fixes in JavaScript or TypeScript repositories. No subagents, no automated review. Everything runs in the main session with the user in the loop. For changes that need a formal HLD (High-Level Design), use the `understand` skill instead.

This skill assumes the repository defines its own lint and test commands. If a required command is not available for a step below, **STOP and ask the user** how to proceed.

## Step 1: Understand

Invoke the `my-explore` skill to load code navigation methodology. Then explore the codebase to understand the requirement or bug.

- Explore relevant source files, trace call chains, check existing behavior
- If anything is unclear, **STOP and ask the user** - do not guess or assume
- Repeat until the requirement or bug is fully understood with no open questions

After exploring, **STOP and present the understanding to the user**:
- Summarize the requirement or bug, affected files, and what needs to change
- If you have any remaining questions or uncertainties, ask them now
- Wait for the user to confirm, correct, or add details
- Repeat until the user explicitly confirms the understanding is complete
- Do NOT proceed to Step 2 until the user confirms

## Step 1.5: Trivial Change Check

After understanding is confirmed, evaluate whether the change is **trivial**. A change is trivial when **both** conditions are met:

1. **The planned implementation change is a single contiguous edit block of 5 lines or fewer** and does not introduce a complete new method, component, or function
2. **Low-risk category**: typo fix, constant or config value change, copy or comment edit, import reorder, type annotation addition, or variable rename

If trivial, **skip Step 2 and Step 3** and jump directly to Step 4 (Implement). This skips test planning and new test authoring only. Later verification steps still apply. Inform the user:

> Trivial low-risk change (single contiguous edit block of 5 lines or fewer, category: [specific category]). Skipping test planning and new test authoring and proceeding to implementation.

**Not trivial**, even if the planned implementation change fits the size limit above:
- Conditional logic or branching changes
- Algorithm or formula modifications
- Data transformation or state management changes
- API request or response handling changes
- Security-related code such as auth, permissions, or validation

These cases require the full workflow regardless of line count.

## Step 2: Test Cases

Load general test rules from `/Users/Woo/.agents/skills/auto-testcase/general.md` first. These apply to all test types.

### 2a. Unit Tests (default)

1. Load unit test rules from `/Users/Woo/.agents/skills/auto-testcase/unit.md`
2. Based on the requirement understanding from Step 1 and the unit test rules, draft a unit test plan. Include which functions or modules to test, what scenarios to cover, and the expected behavior for each case.
3. **STOP and present the test plan to the user** for review. The user may approve, remove cases, add cases, or adjust scope.
4. **STOP and wait** after each round. Repeat until the user confirms the final plan.
5. Write the unit test code after confirmation.

### 2b. Integration or E2E Tests (user-driven)

After unit tests are done, **STOP and ask the user**:

> Do you need integration or E2E tests?

- If the user says no, proceed to Step 3.
- If the user says yes, the user specifies what to test. Do not recommend test cases. Write tests for exactly what the user describes.
  1. Load the relevant rules: `/Users/Woo/.agents/skills/auto-testcase/integration.md` and/or `/Users/Woo/.agents/skills/auto-testcase/e2e.md`
  2. Clarify scope if needed, including mock boundaries, user journeys, and setup requirements. Wait until the requested scope is explicit.
  3. Write the test code, then proceed to Step 3

## Step 3: Review Test Code

If the user skipped all test types in Step 2, skip directly to Step 4.

After all test code is written, **STOP and ask the user**:

> Test code complete. Would you like to review the test code before I start implementation?
> - Unit: [files written or skipped]
> - Integration: [files written or skipped]
> - E2E: [files written or skipped]

- If the user wants to review, wait for feedback, apply changes, then ask if further review is needed.
- If the user says no review is needed, or gives another clear affirmative response, proceed to Step 4.
- Do NOT proceed to Step 4 until the user explicitly confirms.

## Step 4: Implement

Automatically load the relevant project standards based on the files you expect to change at that point. Do not ask the user for confirmation. Load and apply them directly. If the implementation scope expands later, load any newly relevant rule files before editing those additional files.

| Condition | File to Read |
|---|---|
| TypeScript (`.ts` or `.tsx` files) | `/Users/Woo/.code/shared-rules/common/typescript.md` |
| Any browser frontend (`.vue`, `.tsx`, `.jsx`, or browser-rendered `.ts` or `.js` modules) | `/Users/Woo/.code/shared-rules/frontend/architecture.md` |
| Vue (`vue` in dependencies and the task touches browser-rendered UI) | `/Users/Woo/.code/shared-rules/frontend/vue3.md` |
| React (`react` in dependencies and the task touches browser-rendered UI) | `/Users/Woo/.code/shared-rules/frontend/reactjs.md` |
| Next.js (`next` in dependencies) | `/Users/Woo/.code/shared-rules/frontend/nextjs.md` |
| Next.js fullstack (`next` plus database operations) | `/Users/Woo/.code/shared-rules/frontend/nextjs-fullstack.md` |
| Any backend (non-frontend `.ts` or `.js` files) | `/Users/Woo/.code/shared-rules/backend/ddd.md` |
| Express (`express` in dependencies) | `/Users/Woo/.code/shared-rules/backend/express.md` |
| MongoDB (`mongoose` or `mongodb` in dependencies) | `/Users/Woo/.code/shared-rules/backend/mongodb.md` |

Read the matching rule files, then implement. Keep changes minimal and focused.

## Step 5: Review Implementation

After implementation is complete, **STOP and ask the user**:

> Implementation complete. Would you like to review the code before running lint and tests?

- If the user wants to review, wait for feedback, apply changes, then ask if further review is needed.
- If the user says no review is needed, or gives another clear affirmative response, proceed to Step 6.
- Do NOT proceed to Step 6 until the user explicitly confirms.

## Step 6: Lint

Run the repository lint command for the affected package or workspace. Prefer the command defined in the relevant `package.json`, for example `npm run lint`, `pnpm lint`, `yarn lint`, or `bun run lint`. Fix all errors. If the same issue persists through **3 consecutive fix attempts**, trigger the **Stuck Escalation** process below.

## Step 7: Unit and Integration Tests

Run the relevant unit and integration test commands for the affected package or workspace. If Vitest is configured, use the project's Vitest command, for example `npx vitest run` or the package-manager equivalent.

If tests fail:
- **Your code has a bug**: fix your code and re-run.
- **A test case needs modification**: **STOP and ask the user** before changing any test. Explain what the test expects versus what your code does, and let the user decide.

**FORBIDDEN**: modifying test cases without user approval.

If the same issue persists through **3 consecutive fix attempts**, trigger the **Stuck Escalation** process below.

## Step 8: E2E Tests (if applicable)

If E2E test cases were written in Step 2b, **STOP and ask the user**:

> Previous test steps complete. Run E2E tests now?

- If the user says no, skip to Step 9.
- If the user says yes, run the configured E2E test command for the affected app or workspace. Common examples:
  - Web: `npx playwright test`
  - React Native: `maestro test .maestro/`
- If tests fail, apply the same rules as Step 7.
- If the same issue persists through **3 consecutive fix attempts**, trigger the **Stuck Escalation** process below.

If no E2E test cases were written, skip directly to Step 9.

## Stuck Escalation

When the same issue persists through 3 consecutive fix attempts in any step:

This escalation process does not override earlier approval gates. In particular, if the next attempt would require changing a test case, you must still get user approval first.

1. **Re-analyze**: stop fixing symptoms. Re-read the failing code and error output from scratch. Identify the root cause, not the surface error.
2. **Research**: search the web for the specific error or pattern. Query GitHub issues, Stack Overflow, Reddit, and technical blogs. Look for known issues, correct API usage patterns, and community-recommended workarounds.
3. **Try a new approach**: based on the research, implement a fundamentally different solution rather than iterating on the same failing approach. Explain to the user what you found and why you are changing strategy.

If the new approach also fails after 3 consecutive fix attempts, **STOP and present the situation to the user** with all research findings and attempted approaches. Let the user decide the next step.

## Step 9: Done

Report what was changed:
- Files modified or created
- Tests run, passed, or skipped
- Lint status
