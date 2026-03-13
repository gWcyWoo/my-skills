---
name: selfcheck-testcase-design
description: Test plan design validation. Called by testcase workflow after Step 1. Dispatches Codex for independent audit, then self-iterates fixes until zero issues.
---

# Selfcheck — Test Plan Design Validation

Independent audit of test plan before user confirmation. This is a critical gate — the test plan must fully cover ALL requirements before any code is written.

## When to Use

After completing testcase Step 1 (Design Test Cases), before presenting the plan to the user.

## Process

### Step 1: Prepare Inputs

Collect these two artifacts:
1. **Requirement Output** — The confirmed `understand` output (requirements analysis with ALL acceptance criteria)
2. **Draft Test Plan** — The test plan table from testcase Step 1

### Step 2: Audit via Codex

Read the audit prompt template from `~/.claude/skills/selfcheck-testcase-design/audit-prompt.md`.

Invoke the `codex` skill with `sandbox: read-only`. Construct the Codex prompt by combining:
- The full audit prompt template
- The two inputs from Step 1 substituted into `[Requirement Output]` and `[Target Test Plan]`

### Step 3: Process Codex Result

Parse the Codex output for **Status** and **Violations**.

- **100% COMPLIANT with 0 violations** → Go to Step 5
- **Violations found** → Go to Step 4

### Step 4: Fix-and-Self-Review Loop

For each violation reported by Codex:

1. **Fix the test plan** — Add missing tests, remove orphans, strengthen hollow tests, eliminate redundancy
2. **Scoped self-review** — ONLY verify that each reported violation has been correctly fixed. Do NOT expand audit scope.
   - For each Codex violation ID, confirm: Is the fix applied? Does it resolve the issue?
   - **Scope boundary**: If a fix is correct, move on. Do not re-audit unrelated parts.
3. **If a fix introduces a new issue** — Fix that specific regression and re-verify it only
4. **If all fixes verified** → Go to Step 5

**Self-review rules:**
- Review ONLY the changed portions of the test plan
- Check ONLY whether each Codex-reported violation is resolved
- Do NOT flag new issues that Codex did not report — Codex already performed the exhaustive audit
- Output a simple checklist: `[violation ID] — Fixed: Y/N`

### Step 5: Complete

Once zero issues confirmed, return the validated test plan to the testcase workflow.
