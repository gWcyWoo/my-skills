---
name: tdd
description: Lightweight TDD for small requirements and bug fixes. Runs entirely in the main session — no subagents, no automated review. Optional lightweight HLD for larger changes. User stays in the loop throughout.
---

# TDD

Lightweight flow for small requirements and bug fixes. No subagents, no automated review. Optional lightweight HLD for larger changes. Everything runs in the main session with the user in the loop.

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

## Step 2: HLD (Optional)

**STOP and ask the user**:

> Do you need a lightweight HLD before writing tests? (Small changes can skip this)

- If the user says no → skip to Step 3.
- If the user says yes:
  1. Based on the requirement understanding (Step 1), draft a lightweight HLD — signatures and types only, no implementation details:
     - New/modified function signatures (name, params, return type)
     - New/modified type definitions, interfaces, data structures
     - Module/component boundaries if relevant
  2. **STOP and present the HLD to the user** for review. Wait for confirmation.
  3. After confirmation, write the skeleton code: interfaces, types, function stubs (body throws `new Error('not implemented')` or returns a default value). No implementation logic. Then proceed to Step 3.

## Step 3: Test Cases

Load general test rules from `~/.claude/skills/auto-testcase/general.md` first. These apply to all test types.

Ask each test type sequentially. For each type, **STOP and wait** for the user's reply before moving to the next type.

### 3a. Unit Tests

**STOP and ask the user**:

> Do you need unit tests?

- If the user says no → skip to Step 3b.
- If the user says yes:
  1. Load unit test rules from `~/.claude/skills/auto-testcase/unit.md`
  2. Based on the requirement understanding (Step 1), the HLD/skeleton (Step 2) if applicable, and the unit test rules, draft a unit test plan. Include: which functions/modules to test, what scenarios to cover (happy path, edge cases, error handling), and expected behavior for each case.
  3. **STOP and present the test plan to the user** for review. The user may approve, remove cases, add cases, or adjust scope.
  4. **STOP and wait** after each round — repeat until the user confirms the final plan.
  5. Write the unit test code after confirmation.

### 3b. Integration Tests

**STOP and ask the user**:

> Do you need integration tests? If yes, tell me what to test (e.g., "cross-module sharing flow", "form submission + API call").

- If the user says no → skip to Step 3c.
- If the user says yes:
  1. Load integration test rules from `~/.claude/skills/auto-testcase/integration.md`
  2. Ask the user what integration test cases they want. Suggest candidates based on the requirement and HLD (if applicable), but let the user decide. Discuss each case — clarify mock boundaries, cross-module interactions.
  3. **STOP and wait** after each round — repeat until the user confirms the final list.
  4. Write the integration test code after confirmation.

### 3c. E2E Tests

**STOP and ask the user**:

> Do you need E2E tests? If yes, tell me what to test (e.g., "login flow end-to-end", "checkout journey").

- If the user says no → skip to Step 4.
- If the user says yes:
  1. Load E2E test rules from `~/.claude/skills/auto-testcase/e2e.md`
  2. Ask the user what E2E test cases they want. Suggest candidates based on the requirement and HLD (if applicable), but let the user decide. Discuss each case — clarify user journeys, setup requirements.
  3. **STOP and wait** after each round — repeat until the user confirms the final list.
  4. Write the E2E test code after confirmation.

## Step 4: Review Test Code

If the user skipped all test types in Step 3, skip directly to Step 5.

After all test code is written, **STOP and ask the user**:

> Test code complete. Would you like to review the test code before I start implementation?
> - Unit: [files written / skipped]
> - Integration: [files written / skipped]
> - E2E: [files written / skipped]

- If the user wants to review → wait for feedback, apply changes, then ask if further review is needed.
- If the user says no review needed (or equivalent: "ok", "继续", "开始编码", "proceed") → proceed to Step 5.
- Do NOT proceed to Step 5 until the user explicitly confirms.

## Step 5: Implement

Select which project standards to load. Based on the requirement understanding (Step 1), determine which rule files are relevant to this specific change. Available rule files:

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

**STOP and present** your selection using the exact file paths. For each file, state whether to load or skip and why. Example:

> - ✅ `/Users/Woo/.code/shared-rules/common/typescript.md` — .tsx files involved
> - ✅ `/Users/Woo/.code/shared-rules/frontend/architecture.md` — component structure change
> - ✅ `/Users/Woo/.code/shared-rules/frontend/reactjs.md` — React component
> - ⬚ `/Users/Woo/.code/shared-rules/frontend/vue3.md` — not a Vue project
> - ⬚ (other irrelevant files...)

Wait for the user to confirm before loading.

After confirmation, read the approved rule files, then implement. If skeleton code was written in Step 2, fill in the stubs. Otherwise write the code from scratch. Keep changes minimal and focused.

## Step 6: Review Implementation Code

After implementation is complete, **STOP and ask the user**:

> Implementation complete. Would you like to review the code before running lint and tests?

- If the user wants to review → wait for feedback, apply changes, then ask if further review is needed.
- If the user says no review needed (or equivalent: "ok", "继续", "跑测试", "proceed") → proceed to Step 7.
- Do NOT proceed to Step 7 until the user explicitly confirms.

## Step 7: Lint

Run `lint 2>/dev/null`. Fix all errors. If the same error persists after **3 consecutive fix attempts**, trigger the **Stuck Escalation** process (see below).

## Step 8: Unit/Integration Tests

Run `npx vitest run 2>/dev/null`.

If tests fail:
- **Your code has a bug** → fix your code, re-run.
- **A test case needs modification** → **STOP and ask the user** before changing any test. Explain what the test expects vs. what your code does, and let the user decide.

**FORBIDDEN**: Modifying test cases without user approval.

If the same issue fails **3 consecutive times**, trigger the **Stuck Escalation** process (see below).

## Step 9: E2E Tests (if applicable)

If E2E test cases were designed in Step 3c, **STOP and ask the user**:

> Previous test steps complete. Run E2E tests now?

- If the user says no → skip to Step 10.
- If the user says yes → run E2E tests. Detect platform — Web: `npx playwright test`, React Native: `maestro test .maestro/`
  - If tests fail, apply the same rules as Step 8 (fix code bugs; ask user before modifying tests).
  - If the same issue fails **3 consecutive times**, trigger the **Stuck Escalation** process (see below).

If no E2E test cases were designed, skip directly to Step 10.

## Stuck Escalation

When the same error persists after 3 consecutive fix attempts in any step:

1. **Re-analyze** — Stop fixing symptoms. Re-read the failing code and error output from scratch. Identify the root cause, not the surface error.

2. **Research** — Search for solutions externally. Use WebSearch to query GitHub issues, Stack Overflow, Reddit, and technical blogs for the specific error or pattern. Look for:
   - Known issues with the libraries/frameworks involved
   - Correct API usage patterns
   - Community-recommended workarounds

3. **Try a new approach** — Based on the research, implement a fundamentally different solution rather than iterating on the same failing approach. Explain to the user what you found and why you're changing strategy.

If the new approach also fails after 3 attempts, **STOP and present the situation to the user** with all research findings and attempted approaches. Let the user decide the next step.

## Step 10: Done

Report what was changed:
- Files modified/created
- Tests passed
- Lint status
