---
name: tdd
description: Use after HLD design is confirmed. Orchestrates test case and code implementation in the main process, then dispatches review subagents.
---

# TDD Workflow

Implements test cases and code in the main process based on the confirmed HLD design contract. Reviews are dispatched to subagents after implementation.

## Input Constraint

**The sole input is the confirmed HLD design output.** All test cases and implementation must be derived strictly from the HLD contracts (interfaces, function signatures, modules, flow).

## Process

### Step 1: Write Test Cases (main process)

Invoke the `testcase` skill inline. Design test plan, selfcheck, write test code, and self-review — all in the main process. The user sees every step.

### Step 2: Implement Code (main process)

Invoke the `code` skill inline. Load standards, implement against HLD contracts, and self-review — all in the main process. The user sees every step.

### Step 3: GREEN Test + Type Check

Run BOTH commands in the main process:

```bash
npx vitest run 2>/dev/null
```

**Expected outcome:** All tests GREEN. Zero type errors. All previously passing tests remain GREEN.

### Step 4: Fix Failures (if any)

If any tests or type-check fail, fix directly in the main process:

1. Read the failing test to understand what it expects
2. Read the implementation to find the mismatch
3. Fix the implementation (or the test if the test has a defect)
4. Re-run until all GREEN + zero type errors

**STOP HERE — HARD GATE.**
You MUST output the following evidence table before proceeding to Step 6. If this table is empty or absent, the workflow is INVALID.

```
## Review Evidence
| Reviewer | Issues Found | Issues Fixed | Re-run Result |
|----------|-------------|-------------|---------------|
| Test Reviewer | [count] | [count] | GREEN / FAIL |
| Code Reviewer | [count] | [count] | GREEN / FAIL |
```

If either reviewer reports issues, you MUST fix them and re-run tests + type-check. Do NOT proceed until both rows show 0 remaining issues and GREEN re-run.

### Step 6: Complete

All tests GREEN AND type-check passes AND review evidence table present with 0 remaining issues → TDD workflow complete.
