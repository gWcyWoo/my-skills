---
name: auto-tdd
description: Fully automated TDD pipeline. Takes a user requirement and executes understand → Codex audit → testcase → code → verify with zero human intervention.
---

# Auto-TDD Pipeline

Fully automated pipeline from requirement to verified code. Zero human intervention — user only provides the requirement.

## Execution Model

This skill orchestrates existing skills by **reading their SKILL.md files** for process details. It does NOT invoke skills via the Skill tool. Phases execute either inline or in subagents — subagents are used when isolating context benefits subsequent phases (see individual phase instructions).

**GATE OVERRIDE**: When following a sub-skill's process, bypass ALL **user-confirmation gates** — instructions that say "present to user and ask", "please confirm before I proceed", "wait for user confirmation", or "STOP" at the end of a completed phase. Treat these as phase-complete markers and proceed to the next phase automatically.

**PRESERVE prerequisite checks**: Instructions that say "if [artifact/input] is missing, ask the user and STOP" are NOT confirmation gates — they are error conditions. If a prerequisite check triggers, write the error to `error.md` and stop the pipeline.

## Artifact Recording

All intermediate outputs are written to files instead of being displayed in conversation. The model still generates content normally — it writes the content to artifact files using the Write tool instead of outputting text blocks to the user. This keeps conversation context clean for subsequent phases and provides a full audit trail.

### Directory Structure

At pipeline start, create the artifact directory under the **project root** (current working directory):

```
.auto-tdd/{requirement_name}/
├── progress.md                # Pipeline progress tracker — updated at each phase boundary
├── understand_hld.md          # Phase 1: original Requirements Analysis + HLD Design
├── understand_hld_audit.md    # Phase 2: Codex audit issues (only if violations found)
├── understand_hld_final.md    # Phase 2: post-fix version (only if violations found; if PASS, not created — understand_hld.md is the final)
├── testcase.md                # Phase 3: test types, test plan, correspondence table
├── code.md                    # Phase 4: implementation checklist, traceability, verification
└── error.md                   # Only created if pipeline fails
```

**`{requirement_name}`**: Derive a short, filesystem-safe name from the user's requirement (e.g., "add-share-feature", "fix-login-redirect"). Use lowercase kebab-case, max 50 chars.

### Recording Rules

1. **Write phase results to artifact files, not to conversation** — use the Write tool to save content to the corresponding artifact file
2. **Only display to user**: Phase transition markers (one line each) and the final summary
3. **Artifact files are immutable after creation** — never overwrite or append to a file written by a prior phase. If a phase produces a revised version (e.g., post-audit fix), write it as a new file (e.g., `understand_hld_final.md`), keeping the original intact for audit comparison
4. **Before reading ANY file, check if its content is already in conversation context** (loaded by a prior phase, a prior skill, or a prior Read call). If yes, use the in-context content directly — do NOT Read the file again. This applies to artifact files, skill files, rule files, project source files, and all other files

## Progress Tracking

### progress.md Format

```
requirement: {user's original requirement text}
phase1: done | pending
phase2: done | pending
phase3: done | pending
phase4: done | pending
phase5: done | pending
```

**Update rules**:
- Create `progress.md` at pipeline start with all phases set to `pending`
- After each phase completes successfully, update the corresponding line to `done`
- `progress.md` is the ONLY artifact file that is mutable — it is updated at each phase boundary

### Resume on Context Exhaustion

When auto-tdd is invoked and a `.auto-tdd/{requirement_name}/progress.md` already exists:

1. Read `progress.md` to determine the last completed phase
2. Read the artifact files for all completed phases to restore context (this is an exception to Recording Rule 4 — on resume, you MUST Read artifact files since prior context is lost)
3. Resume from the first `pending` phase
4. Display: `▶ Resuming from Phase N: ...`

**Phase-specific resume behavior**:
- **Resume at Phase 2**: Read `understand_hld.md` → run Codex audit
- **Resume at Phase 3**: Read `understand_hld_final.md` (or `understand_hld.md` if no final) → run testcase
- **Resume at Phase 4**: Read the authoritative understand_hld artifact + `testcase.md` → run code
- **Resume at Phase 5**: No artifact read needed — just run vitest + lint

## Pipeline

```
Phase 1: understand + hld
Phase 2: understand-hld-check (Codex audit)
Phase 3: testcase
Phase 4: code
Phase 5: verify (vitest + lint)
```

## Failure Handling (applies to all phases)

Any phase can fail. When a phase encounters an unresolvable error:

1. Write the failure details to `error.md` with the phase name, error description, and what was attempted
2. Stop the pipeline — do NOT proceed to subsequent phases
3. Display the failure report to the user

Specific failure scenarios:
- **Phase 1**: Self-check gate (subagent-instructions Step 3b) cannot be satisfied → fail
- **Phase 2**: Codex audit violations cannot be fixed after applying all suggested fixes → fail
- **Phase 2**: Codex subagent fails to execute (network error, CLI error) → retry once, then fail
- **Phase 3**: Testcase subagent fails (binding inputs missing, lint errors unfixable, subagent error) → fail
- **Phase 4**: Traceability or checklist verification has unfixable ❌ → fail
- **Phase 5**: Verify fails after 3 retries → fail

---

### Phase 1: Requirements + Design

Read `~/.claude/skills/understand/subagent-instructions.md` and `~/.claude/skills/hld/SKILL.md`. Execute their full process:

1. Classify task type (subagent-instructions Step 1)
2. Analyze requirements (subagent-instructions Step 2) — including Affected Files and Acceptance Criteria
3. Execute HLD design (subagent-instructions Step 3 / hld Step 0–2) — load architecture rules, design interfaces/signatures/boundaries/flows
4. Execute self-check gate (subagent-instructions Step 3b) — all 5 checks must pass with structured evidence
5. Produce combined output (subagent-instructions Output section format)

**Gate bypass**: Skip understand Step 3 user confirmation. Proceed directly to Phase 2.

**Record**: Read `~/.claude/skills/save-hld-record/SKILL.md`. Execute Step 2 to write `understand_hld.md` — use the pipeline's already-determined `{requirement_name}` (from Directory Structure), not save-hld-record Step 1's derivation logic. This file is the Phase 1 original output and is never modified after creation.

---

### Phase 2: Codex Audit

Read `~/.claude/skills/understand-hld-check/SKILL.md`. Execute:

1. Prepare inputs: User's Original Request, Requirements Analysis, HLD Design, CLAUDE.md path
2. Dispatch subagent with audit prompt (understand-hld-check Step 2)
3. Parse result:
   - **100% COMPLIANT** → proceed to Phase 3. No additional files created — `understand_hld.md` is the final authoritative artifact.
   - **Violations found** → fix artifacts per understand-hld-check Step 4, self-review fixes. Then execute `save-hld-record` Steps 4–5 to write `understand_hld_audit.md` and `understand_hld_final.md`. Proceed to Phase 3.

**Constraint**: Do NOT proceed to Phase 3 with known unfixed violations.

**Data flow**: If `understand_hld_final.md` exists (audit found and fixed violations), all subsequent phases (Phase 3, Phase 4) MUST use the post-fix versions from that file. If it does not exist (audit passed), use `understand_hld.md`. Never modify `understand_hld.md` after Phase 1 — it is the immutable original for audit comparison.

---

### Phase 3: Test Cases

Launch an Agent subagent (general-purpose) to execute testcase generation. This isolates test design noise from the main session, preserving context for Phase 4 (implementation).

**Subagent prompt must contain:**
1. The authoritative HLD content — read `understand_hld_final.md` if it exists, otherwise `understand_hld.md`, and include the full text in the prompt
2. The artifact directory path: `.auto-tdd/{requirement_name}/`
3. Instruction: "Read `~/.claude/skills/testcase/SKILL.md` and execute the full process. Do NOT invoke any skills via the Skill tool — you are already executing the testcase workflow by reading SKILL.md directly. Bypass ALL user-confirmation STOP gates — proceed directly without waiting. After writing test code and passing lint, write the artifact file to `.auto-tdd/{requirement_name}/testcase.md` with sections: `## Test Types`, `## Test Plan`, `## Correspondence`. Return with `STATUS: COMPLETE` when done. Do NOT invoke the `code` skill."

**Gate bypass**: The subagent bypasses all three STOP gates in testcase SKILL.md (Step 0, Step 1, Step 2).

**Binding inputs**: The authoritative HLD content is provided in the subagent prompt.

**On subagent completion**: Verify `testcase.md` artifact was written. Proceed to Phase 4.

---

### Phase 4: Implementation

Read `~/.claude/skills/code/SKILL.md`. Execute:

1. **Load project standards** (code Step 1)
2. **Read reference code** (code Step 1b)
3. **Compile implementation checklist** (code Step 1c)
4. **Implement** (code Step 2a–2b): Locate binding inputs, write implementation code to the project
5. **Traceability** (code Step 2c): Forward, reverse, and flow edge traceability — all must pass
6. **Checklist verification** (code Step 2d): Every item must be satisfied

**Constraint**: Any traceability ❌ or checklist ❌ is a blocker. Fix the code, re-verify. If unfixable, fail the pipeline.

**Binding inputs**: Same rule as Phase 3 — use post-fix artifacts if Phase 2 produced them.

**Record**: Write to `code.md`:
- `## Implementation Checklist` — the checklist from Step 1c
- `## Traceability` — forward, reverse, and flow edge tables
- `## Checklist Verification` — final verification table

---

### Phase 5: Verify

Run both verification commands:

```bash
npx vitest run 2>/dev/null
lint 2>/dev/null
```

**If ALL GREEN** → Pipeline complete. Output final summary to user.

**If FAIL** → Enter self-fix loop:

1. Analyze failure output (which tests fail, which lint errors)
2. Fix the code — only the minimum change to resolve the failure
3. Re-run verification
4. Repeat up to **3 times**

**If still failing after 3 retries** → Write failure report to `error.md` and display to user:

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
**Artifacts**: .auto-tdd/{requirement_name}/
```

On failure, display the failure report from `error.md`.

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

Each `##` heading is the `requirement_name` (used for the artifact directory). The content under it is the requirement description.

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

**Subagent isolation**: Each subagent gets a fresh context window. No context pollution between requirements. No `/clear` needed.

**Failure handling**: A failed requirement does NOT block subsequent requirements. The main session records the failure and continues. After all requirements are processed, display the summary table.

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

| # | Requirement | Status | Tests | Artifacts |
|---|-------------|--------|-------|-----------|
| 1 | add-share-button | ✅ PASS | 12 passed | .auto-tdd/add-share-button/ |
| 2 | fix-login-redirect | ❌ FAIL | Phase 4 | .auto-tdd/fix-login-redirect/error.md |
| 3 | update-user-profile | ✅ PASS | 8 passed | .auto-tdd/update-user-profile/ |
```

---

## Rules

1. **No human intervention** — all user-confirmation gates in sub-skills are bypassed; prerequisite checks are preserved
2. **No skill modification** — sub-skills are read for process details only, not invoked via Skill tool
3. **Codex audit is mandatory** — always runs, never skipped
4. **Failure stops the pipeline** — do not proceed past a failed phase; write error.md and report
5. **Sub-skill process is authoritative** — follow each skill's detailed steps exactly, only bypassing confirmation gates
6. **Silent execution** — intermediate outputs go to artifact files via Write tool, not to conversation
7. **Artifact integrity** — every phase must write its artifact file before proceeding to the next phase
8. **Post-audit authority** — if Phase 2 modifies artifacts, all subsequent phases use the modified versions
