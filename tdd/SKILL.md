---
name: tdd
description: Default development workflow. TDD for requirements and bug fixes. Runs entirely in the main session — no subagents, no automated review. User stays in the loop throughout.
---

# TDD

Default development workflow. No subagents, no automated review. Everything runs in the main session with the user in the loop. For changes that need a formal HLD (High-Level Design), use the `understand` skill instead.

## Step 1: Understand

Invoke the `my-explore` skill to load code navigation methodology. Then explore the codebase to understand the requirement or bug.

- Explore relevant source files, trace call chains, check existing behavior
- If anything is unclear, **STOP and ask the user** — do not guess or assume
- Repeat until the requirement/bug is fully understood with no open questions

After exploring, **STOP and present the understanding to the user**:
- Summarize the requirement or bug, affected files, and what needs to change
- If you have any remaining questions or uncertainties, ask them now
- Wait for the user to confirm, correct, or add details
- Repeat until the user explicitly confirms the understanding is complete
- Do NOT proceed to Step 2 until the user confirms

## Step 1.5: Trivial Change Check

After understanding is confirmed, evaluate whether the change is **trivial**. A change is trivial when **both** conditions are met:

1. **Contiguous diff ≤ 5 lines** and does not introduce a complete new method, component, or function
2. **Low-risk category**: typo fix, constant/config value change, copy/comment edit, import reorder, type annotation addition, variable rename

If trivial → **skip Step 2 (all tests)**, jump directly to Step 4 (Implement). Inform the user:

> Trivial low-risk change (≤ 5 lines, category: [specific category]). Skipping tests — proceeding to implementation.

**Not trivial** (even if ≤ 5 lines):
- Conditional logic or branching changes
- Algorithm or formula modifications
- Data transformation or state management changes
- API request/response handling changes
- Security-related code (auth, permissions, validation)

These cases require the full workflow regardless of line count.

## Step 2: Test Cases

Load general test rules from `~/.claude/skills/auto-testcase/general.md` first. These apply to all test types.

### 2a. Unit Tests (system-recommended)

1. Load unit test rules from `~/.claude/skills/auto-testcase/unit.md`
2. Based on the requirement understanding (Step 1) and the unit test rules, draft a unit test plan. Include: which functions/modules to test, what scenarios to cover (happy path, edge cases, error handling), and expected behavior for each case.
3. **STOP and present the test plan to the user** for review. The user may approve, remove cases, add cases, or adjust scope.
4. **STOP and wait** after each round — repeat until the user confirms the final plan.
5. Write the unit test code after confirmation.

### 2b. Integration / E2E Tests (user-driven)

After unit tests are done, **STOP and ask the user**:

> Do you need integration or E2E tests?

- If the user says no → proceed to Step 3.
- If the user says yes — the user specifies what to test. Do not recommend test cases. Write tests for exactly what the user describes.
  1. Load the relevant rules: `~/.claude/skills/auto-testcase/integration.md` and/or `~/.claude/skills/auto-testcase/e2e.md`
  2. Clarify scope if needed (mock boundaries, user journeys, setup requirements).
  3. Write the test code, then **STOP and wait** for the user to confirm before proceeding.

## Step 3: Review Test Code

If the user skipped all test types in Step 2, skip directly to Step 4.

After all test code is written, **STOP and ask the user**:

> Test code complete. Would you like to review the test code before I start implementation?
> - Unit: [files written / skipped]
> - Integration: [files written / skipped]
> - E2E: [files written / skipped]

- If the user wants to review → wait for feedback, apply changes, then ask if further review is needed.
- If the user says no review needed (or equivalent: "ok", "继续", "开始编码", "proceed") → proceed to Step 4.
- Do NOT proceed to Step 4 until the user explicitly confirms.

## Step 4: Implement

Automatically load the relevant project standards based on the files being changed. Do not ask the user for confirmation — just load and apply.

| Condition | File to Read |
|---|---|
| TypeScript (`.ts`/`.tsx` files) | `/Users/Woo/.code/shared-rules/common/typescript.md` |
| Any frontend (`.vue`/`.tsx`/`.jsx` files) | `/Users/Woo/.code/shared-rules/frontend/architecture.md` |
| Vue (`vue` in dependencies) | `/Users/Woo/.code/shared-rules/frontend/vue3.md` |
| React (`react` in dependencies) | `/Users/Woo/.code/shared-rules/frontend/reactjs.md` |
| Next.js (`next` in dependencies) | `/Users/Woo/.code/shared-rules/frontend/nextjs.md` |
| Next.js fullstack (`next` + database operations) | `/Users/Woo/.code/shared-rules/frontend/nextjs-fullstack.md` |
| Any backend (non-frontend `.ts`/`.js` files) | `/Users/Woo/.code/shared-rules/backend/ddd.md` |
| Express (`express` in dependencies) | `/Users/Woo/.code/shared-rules/backend/express.md` |
| MongoDB (`mongoose`/`mongodb` in dependencies) | `/Users/Woo/.code/shared-rules/backend/mongodb.md` |

Read the matching rule files, then implement. Keep changes minimal and focused.

## Step 5: Review Implementation

After implementation is complete, **STOP and ask the user**:

> Implementation complete. Would you like to review the code before running lint and tests?

- If the user wants to review → wait for feedback, apply changes, then ask if further review is needed.
- If the user says no review needed (or equivalent: "ok", "继续", "跑测试", "proceed") → proceed to Step 6.
- Do NOT proceed to Step 6 until the user explicitly confirms.

## Step 6: Lint

Run `lint 2>/dev/null`. Fix all errors. If the same error persists after **3 consecutive fix attempts**, trigger the **Stuck Escalation** process (see below).

## Step 7: Unit/Integration Tests

Run `npx vitest run 2>/dev/null`.

If tests fail:
- **Your code has a bug** → fix your code, re-run.
- **A test case needs modification** → **STOP and ask the user** before changing any test. Explain what the test expects vs. what your code does, and let the user decide.

**FORBIDDEN**: Modifying test cases without user approval.

If the same issue fails **3 consecutive times**, trigger the **Stuck Escalation** process (see below).

## Step 8: E2E Tests (if applicable)

If E2E test cases were written in Step 2b, **STOP and ask the user**:

> Previous test steps complete. Run E2E tests now?

- If the user says no → skip to Step 9.
- If the user says yes → run E2E tests. Detect platform — Web: `npx playwright test`, React Native: `maestro test .maestro/`
  - If tests fail, apply the same rules as Step 7 (fix code bugs; ask user before modifying tests).
  - If the same issue fails **3 consecutive times**, trigger the **Stuck Escalation** process (see below).

If no E2E test cases were written, skip directly to Step 9.

## Stuck Escalation

When the same error persists after 3 consecutive fix attempts in any step:

1. **Re-analyze** — Stop fixing symptoms. Re-read the failing code and error output from scratch. Identify the root cause, not the surface error.

2. **Research** — Search for solutions externally. Use WebSearch to query GitHub issues, Stack Overflow, Reddit, and technical blogs for the specific error or pattern. Look for:
   - Known issues with the libraries/frameworks involved
   - Correct API usage patterns
   - Community-recommended workarounds

3. **Try a new approach** — Based on the research, implement a fundamentally different solution rather than iterating on the same failing approach. Explain to the user what you found and why you're changing strategy.

If the new approach also fails after 3 attempts, **STOP and present the situation to the user** with all research findings and attempted approaches. Let the user decide the next step.

## Step 9: Done

Report what was changed:
- Files modified/created
- Tests passed
- Lint status
