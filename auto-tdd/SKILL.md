---
name: auto-tdd
description: Fully automated TDD pipeline. Takes a user requirement and executes understand → Codex audit → testcase → code → verify with zero human intervention.
---

# Auto-TDD Pipeline

Fully automated pipeline from requirement to verified code. Zero human intervention — user only provides the requirement.

## Execution Model

Auto-tdd is a **thin automation layer** over the normal manual flow. It executes the same skills in the same order, with the same procedure directory structure. The only difference: all user-confirmation gates are bypassed automatically.

**GATE OVERRIDE**: Bypass ALL **user-confirmation gates** — instructions that say "present to user and ask", "please confirm before I proceed", "wait for user confirmation", "Select next step", or "STOP" at the end of a completed phase. Treat these as phase-complete markers and proceed to the next phase automatically.

**PRESERVE prerequisite checks**: Instructions that say "if [artifact/input] is missing, ask the user and STOP" are NOT confirmation gates — they are error conditions. If a prerequisite check triggers, stop the pipeline and display the error.

## Pipeline

```
Phase 1: understand (understand skill — produces understand.md + hld.md)
Phase 2: audit (understand-hld-check skill — Codex audit + fix)
Phase 3: testcase (testcase skill — test plan + test code)
Phase 4: code (code skill — implementation)
Phase 5: verify (vitest + lint)
```

All phase outputs are written to the same procedure directory: `{project_root}/.claude/procedure/{YYYY-MM-DD}/{name}/`

## Failure Handling

Any phase can fail. When a phase encounters an unresolvable error:

1. Display the failure details to the user with the phase name and error description
2. Stop the pipeline — do NOT proceed to subsequent phases

Specific failure scenarios:
- **Phase 1**: Critical ambiguity encountered (analysis cannot continue) → fail
- **Phase 1**: AC Quality Self-Check cannot be satisfied → fail
- **Phase 2**: Codex audit violations cannot be fixed after fix-and-verify loop → fail
- **Phase 2**: Codex CLI fails to execute (network error, CLI error) → retry once, then fail
- **Phase 3**: Testcase subagent fails (ACs missing, lint errors unfixable, subagent error) → fail
- **Phase 4**: Traceability or checklist verification has unfixable issues → fail
- **Phase 5**: Verify fails after 3 retries → fail

---

### Phase 1: Requirements + Design

1. **Initialize procedure directory**: Determine project root. Generate a short name (≤10 chars). Create `{project_root}/.claude/procedure/{YYYY-MM-DD}/{name}/`. Write `requirement.md` with the user's requirement (and referenced spec file if any).

2. **Dispatch understand subagent**: Launch an Agent subagent (general-purpose) with this prompt:
   - The procedure directory path
   - "First, invoke the `my-explore` skill using the Skill tool to load code navigation methodology."
   - "Read `~/.claude/skills/understand/subagent-instructions.md` and follow it exactly."
   - "Do NOT invoke the `understand` skill via the Skill tool — you are already executing it."

3. **Handle result**:
   - **STATUS: COMPLETE** → Proceed directly to Phase 2. Do NOT present results to the user or ask for selection.
   - **STATUS: NEEDS_CLARIFICATION** → Critical ambiguity. Fail the pipeline.

---

### Phase 2: Codex Audit

**Skip condition**: If Phase 1 produced a no-logic change (no `hld.md`), skip Phase 2 entirely and proceed to Phase 3.

Invoke the `understand-hld-check` skill **using the Skill tool**. This dispatches a subagent that runs Codex CLI, fixes violations if any, and returns STATUS: PASS or STATUS: FIXED.

**Gate bypass**: Skip the "re-present options to user" step after audit completes. Proceed directly to Phase 3.

---

### Phase 3: Test Cases

Launch an Agent subagent (general-purpose) with this prompt:
- The procedure directory path
- "First, invoke the `my-explore` skill using the Skill tool to load code navigation methodology."
- "Read `~/.claude/skills/testcase/SKILL.md` and follow it exactly. Read the analysis from `{procedure_dir}/understand.md`. If `{procedure_dir}/hld.md` exists, also read it for design contracts. Do NOT read `requirement.md`. Do NOT invoke any skills via the Skill tool other than `my-explore`."
- "**IMPORTANT: Do NOT return NEEDS_CONFIRMATION or ask for confirmation at any point. Bypass ALL STOP gates.** Auto-resolve every gate as follows:
  1. **Test type recommendation** (Step 0): Accept all recommended types and proceed.
  2. **Direction selection** (integration §3 / e2e §3): Accept all AI-recommended directions. If AI cannot generate candidates, use 'Data Transform Mismatch' as default direction based on HLD module boundaries.
  3. **AC Gap Check** (integration §6 / e2e §4): Auto-add integration/e2e tests for cross-module/user-facing gaps. Unit-scope ACs go to supplementary unit plan automatically.
  4. **Test plan confirmation** (Step 1): Proceed directly to writing test code.
  5. **Test code ready** (Step 2): Return with `STATUS: COMPLETE`.
  After test code is written and lint-clean, return with `STATUS: COMPLETE`."

Handle subagent result:
- **STATUS: COMPLETE** → Proceed directly to Phase 4. Do NOT present results to the user or ask for confirmation.
- **NEEDS_CONFIRMATION** (subagent ignored the bypass instruction) → Auto-confirm all recommendations and resume the subagent. Repeat until COMPLETE.

---

### Phase 4: Implementation

Invoke the `code` skill **using the Skill tool**, passing the procedure directory path as argument. This dispatches a code subagent that implements based on HLD contracts.

**Gate bypass**: None needed — code skill runs to completion without user gates.

---

### Phase 5: Verify

Run all verification commands in order:

```bash
lint 2>/dev/null
npx vitest run 2>/dev/null
npx playwright test 2>/dev/null
```

1. **lint** — zero type errors
2. **vitest** — unit + integration tests all pass
3. **playwright** — e2e tests all pass (skip if no e2e test files were generated in Phase 3)

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
▶ Phase 1: Requirements + Design...
▶ Phase 2: Codex Audit...
▶ Phase 3: Test Cases...
▶ Phase 4: Implementation...
▶ Phase 5: Verification...
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
2. **Same flow, same data** — uses the exact same skills and procedure directory as the manual flow; no separate artifact system
3. **Codex audit is mandatory for logic changes** — always runs when hld.md exists; skipped for no-logic changes (no hld.md to audit)
4. **Failure stops the pipeline** — do not proceed past a failed phase
5. **Skill invocation** — understand-hld-check and code are invoked via Skill tool (they handle their own subagent dispatch). understand Phase 1 and testcase Phase 3 follow understand/SKILL.md's subagent dispatch pattern directly.
