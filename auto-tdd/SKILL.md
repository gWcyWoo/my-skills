---
name: auto-tdd
description: Fully automated TDD pipeline. Takes a user requirement and executes understand → self-check → testcase → code → verify with zero human intervention.
---

# Auto-TDD Pipeline

Fully automated pipeline from requirement to verified code. Zero human intervention — user only provides the requirement.

## Execution Model

Auto-tdd invokes the **same skills** as the manual flow, in the same order. The only difference: all user-confirmation gates are bypassed automatically.

**GATE OVERRIDE**: Bypass ALL **user-confirmation gates** — instructions that say "present to user and ask", "please confirm before I proceed", "wait for user confirmation", "Select next step", or "STOP" at the end of a completed phase. Treat these as phase-complete markers and proceed to the next phase automatically.

**Auto-resolve rules for specific gates:**
1. **Test type recommendation**: Accept all recommended types and proceed.
2. **Direction selection**: Accept all AI-recommended directions. If AI cannot generate candidates, use 'Data Transform Mismatch' as default direction based on HLD module boundaries.
3. **AC Gap Check**: Auto-add integration/e2e tests for cross-module/user-facing gaps. Unit-scope ACs go to supplementary unit plan automatically.
4. **Test plan confirmation**: Proceed directly to writing test code.
5. **Step 3 user selection** (code/testcase): Auto-select the next pipeline phase.

**PRESERVE prerequisite checks**: Instructions that say "if [artifact/input] is missing, ask the user and STOP" are NOT confirmation gates — they are error conditions. If a prerequisite check triggers, stop the pipeline and display the error.

## Pipeline

```
Phase 1: understand skill (produces understand.md + hld.md + self-check)
Phase 2: testcase skill (test plan + test code)
Phase 3: code skill (implementation)
Phase 4: verify (vitest + lint)
```

All phase outputs are written to the same procedure directory: `{project_root}/.claude/procedure/{YYYY-MM-DD}/{name}/`

## Failure Handling

Any phase can fail. When a phase encounters an unresolvable error:

1. Display the failure details to the user with the phase name and error description
2. Stop the pipeline — do NOT proceed to subsequent phases

---

### Phase 1: Requirements + Design + Self-Check

**Invoke the `understand` skill using the Skill tool.** The understand skill handles everything: creates the procedure directory, writes requirement.md, dispatches the understand subagent, and runs self-check.

   The understand skill will:
   - Dispatch the understand subagent (produces understand.md + hld.md)
   - Run self-check (independent reviewer verifies quality)
   - Present options to user ← **GATE OVERRIDE: skip presentation, proceed to Phase 2**

   If NEEDS_CLARIFICATION → Critical ambiguity. Fail the pipeline.

---

### Phase 2: Test Cases

Invoke the `testcase` skill **using the Skill tool**, passing the procedure directory path.

The testcase skill will:
- Dispatch the testcase subagent
- Handle NEEDS_CONFIRMATION gates ← **GATE OVERRIDE: auto-confirm all gates using the auto-resolve rules above**
- Return STATUS: COMPLETE when test code is written and lint-clean

**Gate bypass**: Proceed directly to Phase 3.

---

### Phase 3: Implementation

Invoke the `code` skill **using the Skill tool**, passing the procedure directory path as argument.

**Gate bypass**: None needed — code skill runs to completion without user gates.

---

### Phase 4: Verify

Run all verification commands in order:

```bash
npx vitest run 2>/dev/null
npx playwright test 2>/dev/null
lint 2>/dev/null
```

1. **vitest** — unit + integration tests all pass. Fix ALL failures, including pre-existing ones.
2. **playwright** — e2e tests all pass. Skip if no e2e test files were generated. Fix ALL failures, including pre-existing ones.
3. **lint** — zero type errors. Fix ALL errors, including pre-existing ones.

**If ALL GREEN** → Pipeline complete. Output final summary to user.

**If FAIL** → Enter self-fix loop:

1. Analyze failure output (which tests fail, which lint errors)
2. Fix the code — only the minimum change to resolve the failure
3. Re-run the failing verification command (not all three)
4. Repeat up to **3 times**

**If still failing after 3 retries** → Display failure report to user:

```
## Auto-TDD Failed

**Phase**: Verify (retry N/3)
**Failing tests**: [list]
**Lint errors**: [list]
**Last fix attempted**: [description]
**Likely root cause**: [design issue / implementation gap / test error]
```

---

## User-Visible Output

During the pipeline, only display phase transition markers:

```
▶ Phase 1: Requirements + Design + Self-Check...
▶ Phase 2: Test Cases...
▶ Phase 3: Implementation...
▶ Phase 4: Verification...
```

On success, display:

```
## Auto-TDD Complete

**Requirement**: [one-line summary]
**Files created/modified**: [list]
**Tests**: [N passed, 0 failed]
**Lint**: clean
**Procedure**: {procedure_dir}/
```

On failure, display the failure report.

---

## Batch Mode

Process multiple requirements sequentially, each in an isolated subagent.

### Invocation

`/auto-tdd batch <file>` where `<file>` is a markdown file with requirements:

```markdown
## add-share-button
首页添加分享按钮，点击后弹出分享面板

## fix-login-redirect
登录成功后未跳转到原页面，修复重定向逻辑
```

Each `##` heading is the requirement name. The content under it is the requirement description.

### Execution

The main session acts as a **lightweight dispatcher** — it does NOT execute any pipeline logic itself.

```
for each requirement in file (sequential, top to bottom):
  1. Dispatch an Agent subagent with:
     - The requirement name and description
     - Instruction: "Read ~/.claude/skills/auto-tdd/SKILL.md and execute the single-requirement pipeline (NOT batch mode) for this requirement"
  2. Wait for subagent to complete
  3. Collect result: pass (with summary) or fail (with error)
  4. Display one-line status to user
  5. Proceed to next requirement regardless of pass/fail
```

**Subagent isolation**: Each subagent gets a fresh context window. No context pollution between requirements.

**Failure handling**: A failed requirement does NOT block subsequent requirements. After all requirements are processed, display the summary table.

### Batch Output

During execution, display one line per requirement:

```
▶ [1/3] add-share-button — running...
✅ [1/3] add-share-button — passed (12 tests, 0 failures)
▶ [2/3] fix-login-redirect — running...
❌ [2/3] fix-login-redirect — failed (Phase 4: traceability)
▶ [3/3] update-user-profile — running...
✅ [3/3] update-user-profile — passed (8 tests, 0 failures)
```

After all requirements complete, display summary:

```
## Auto-TDD Batch Complete

| # | Requirement | Status | Tests | Procedure |
|---|-------------|--------|-------|-----------|
| 1 | add-share-button | PASS | 12 passed | .claude/procedure/2026-03-16/add-share/ |
| 2 | fix-login-redirect | FAIL | Phase 4 | .claude/procedure/2026-03-16/fix-login/ |
| 3 | update-user-profile | PASS | 8 passed | .claude/procedure/2026-03-16/update-user/ |
```

---

## Rules

1. **No human intervention** — all user-confirmation gates are bypassed; prerequisite checks are preserved
2. **Same skills, same flow** — invokes the exact same skills as the manual flow via Skill tool; no direct subagent dispatch or separate logic
3. **Self-check is automatic** — included in Phase 1 via understand skill's Step 2b
4. **Failure stops the pipeline** — do not proceed past a failed phase
