---
name: testcase-check
description: Independent third-party audit of test cases against HLD contracts. Tests that pass this audit are locked — implementation must conform to them. Dispatches subagent to run Codex CLI, then self-iterates fixes until zero issues.
---

# Test Case Third-Party Audit

Independent Codex audit of test code against HLD contracts and test design rules:
- **Test code** is audited against **hld.md** — do tests faithfully translate HLD contracts?
- **Test code** is audited against **test design rules** — are assertions meaningful, mocks correct, coverage complete?
- **Test code** is audited against **understand.md** — is every AC covered?

Tests that pass this audit become the **locked specification**. During implementation (code phase), test failures mean the implementation is wrong — test code must not be modified.

**Execution model**: A single subagent handles the entire audit lifecycle — running Codex CLI, parsing results, fixing violations, and verifying fixes. The main session only dispatches and receives the final result.

## When to Use

Invoked after testcase phase completes (test code written and lint-clean). In auto-tdd, this runs automatically as Phase 3.5 between testcase and code.

## Process

### Step 1: Dispatch Subagent (main session)

The procedure directory path is available from the testcase phase.

Launch an Agent subagent with the following instructions:

1. Read `~/.claude/skills/codex/SKILL.md` for the Codex CLI execution format (model, flags, timeout).
2. Locate test files: read `{procedure_dir}/testcase/plan.md` to find the test file paths listed in the plan.
3. Construct the Codex prompt string (substitute `{procedure_dir}` and test file paths with actual paths):

   ```
   Read the following files, then perform the audit.

   AUDIT TEMPLATE (read first — defines checks and output format):
   ~/.claude/skills/testcase-check/audit-prompt.md

   HLD DESIGN:
   - {procedure_dir}/hld.md

   REQUIREMENTS ANALYSIS:
   - {procedure_dir}/understand.md

   TEST PLAN:
   - {procedure_dir}/testcase/plan.md

   TEST CODE FILES:
   - {test_file_1}
   - {test_file_2}
   - ... (all test files from the plan)

   After reading all files, use them as the content for each template section:
   <HLD> ← hld.md content
   <UNDERSTAND> ← understand.md content
   <TEST_PLAN> ← testcase/plan.md content
   <TEST_CODE> ← all test code files content

   Then execute the audit checks and output results in the format specified in audit-prompt.md.
   ```

4. Execute using the format from `codex/SKILL.md`, passing this prompt string.
5. Write the Codex output to `{procedure_dir}/audit/testcase-result.md`.
6. Parse the Codex output for **Status**:
   - **"STATUS: 100% COMPLIANT"** → Return to main session with `STATUS: PASS`
   - **Violations found** → Read `~/.claude/skills/testcase-check/SKILL.md` Step 2 for the fix-and-verify process. Follow it exactly. Return `STATUS: FIXED` when all violations are resolved.

### Step 2: Fix-and-Verify Loop (in subagent)

This step iterates until all violations are resolved and no new issues are introduced.

#### 2a: Apply All Fixes

For each violation reported by Codex:

1. **Determine fix location** — always the test file(s), never HLD or understand.md (those are already audited and locked).
2. **Apply the fix** — Edit the test file(s). Fixes must align the test with HLD contracts, not change the contract to match the test.

#### 2b: Per-Violation Verification

After all fixes are applied, verify **every single violation** with structured evidence:

```
[ID-01] SIG_DRIFT — "parseNode called with wrong param type"
  Before: test calls parseNode(rawData) where rawData is plain object
  Fix applied: test now calls parseNode(genomeNode) where genomeNode matches HLD's GenomeNode interface
  Contradiction check: search all test files for "parseNode" → 2 other calls found → both already use GenomeNode
  Verdict: FIXED ✓
```

Each verification MUST include:
- **Before**: What the issue was (quote the problematic test code)
- **Fix applied**: What changed (quote the new test code)
- **Contradiction check**: Search test files for the same symbol/pattern — does the fix contradict other tests?
- **Verdict**: FIXED or STILL_BROKEN

#### 2c: Convergence Check

After all violations are verified:

1. Count results: how many FIXED, how many STILL_BROKEN?
2. If any STILL_BROKEN → return to 2a with only the STILL_BROKEN items
3. If all FIXED → proceed to 2d

#### 2d: Lint Gate

Run `lint` on the fixed test file(s). If errors exist, fix them. Repeat until lint-clean.

#### 2e: Regression Scan

Read the modified test code. For each modification, check:
- Does the fix still align with the HLD contract it's supposed to test?
- Does the fix break another test case's assertion logic?
- Does the fix introduce a new mock that violates the mock count rule?

If any regression found → treat it as a new violation and return to 2a.
If no regressions → Return to main session with `STATUS: FIXED`

### Step 3: Handle Subagent Result (main session)

Parse the subagent's returned status:

- **`STATUS: PASS`** — No violations found. Tests are locked. Proceed to code phase.
- **`STATUS: FIXED`** — All violations fixed and verified. Tests are locked. Proceed to code phase.

## Decision Summary

```
Main session: Dispatch subagent
Subagent: Run Codex → Write audit/testcase-result.md → PASS? → return STATUS: PASS
                                                     → FAIL? → Fix tests → Verify → Lint → Regression scan → return STATUS: FIXED
                                                                                                             → regression? → loop
Main session: Receive status → Tests are locked → Proceed to code phase
```

**The subagent does NOT return to the main session with known unfixed violations.**
