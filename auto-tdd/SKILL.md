---
name: auto-tdd
description: Use when `requirement.md`, `understand.md`, and `hld.md` already exist and you want a fully automated, zero-confirmation TDD pipeline.
---

# Auto-TDD Pipeline

Two Codex child agents work in parallel - one writes tests, one writes implementation - both from the same HLD. Each child agent gets adversarial-reviewed by Codex and fixes issues before returning. The main session then runs verification. Zero human intervention.

## Prerequisite

The procedure directory must contain:
- `requirement.md` - the original requirement
- `understand.md` - requirements analysis
- `hld.md` - high-level design contracts

If any of these files are missing, stop and display the error. Do NOT invoke `understand-0` or create these files here - they must be produced before invoking this skill.

## Pipeline

```
Phase 1 (parallel):
├── Child agent A: Codex writes tests -> Codex review -> fix -> lint clean
└── Child agent B: Codex writes implementation -> Codex review -> fix -> lint clean
Phase 2: verify (vitest + e2e + lint)
```

---

### Phase 1: Test Cases + Implementation (parallel child agents)

Launch **both** child agents in parallel. Each is self-contained - writes code, gets reviewed by Codex, fixes issues, and returns lint-clean.

1. **Test cases child agent** - invoke the `auto-testcase` skill using the Skill tool, passing the procedure directory path. The child agent writes tests from HLD, runs Codex adversarial-review, fixes issues, and returns lint-clean test code.

2. **Implementation child agent** - launch a general-purpose child agent with the following prompt:

   ```
   You are implementing the requirement in {procedure_dir}/hld.md. Work independently from start to finish.

   1. Invoke the `my-explore-0` skill using the Skill tool to load code navigation methodology.

   2. Read {procedure_dir}/hld.md for design contracts.

   3. Select and load project standards. Check package.json and file extensions to determine which apply:
      - TypeScript (.ts/.tsx): ~/.agents/shared-rules/common/typescript.md
      - Any frontend (.vue/.tsx/.jsx): ~/.agents/shared-rules/frontend/architecture.md
      - Vue (vue in dependencies): ~/.agents/shared-rules/frontend/vue3.md
      - React (react in dependencies): ~/.agents/shared-rules/frontend/reactjs.md
      - Next.js (next in dependencies): ~/.agents/shared-rules/frontend/nextjs.md
      - Next.js fullstack (next + database operations): ~/.agents/shared-rules/frontend/nextjs-fullstack.md
      - Any backend (non-frontend .ts/.js): ~/.agents/shared-rules/backend/ddd.md
      - Express (express in dependencies): ~/.agents/shared-rules/backend/express.md
      - MongoDB (mongoose/mongodb in dependencies): ~/.agents/shared-rules/backend/mongodb.md

   4. Write implementation code following the HLD interfaces and module boundaries.

   5. Run `lint 2>/dev/null`. Fix until zero errors.

   6. Run /codex:adversarial-review --wait on the files you wrote. Fix any issues found, re-lint. Repeat up to 2 times if issues persist.

   7. Return a summary: files created/modified, review status.

   SKIP ALL STOP GATES - run straight through without user confirmation.
   ```

Wait for **both** child agents to complete. If either fails, stop the pipeline and report the failure.

---

### Phase 2: Verify

Run all verification commands in order:

1. **vitest** - `npx vitest run 2>/dev/null`. All tests pass.
2. **E2E** - detect platform and run. Skip if no e2e test files were generated.
   - **Web** (has `playwright` in devDependencies): `npx playwright test 2>/dev/null`
   - **React Native** (has `react-native` in dependencies): `maestro test .maestro/ 2>/dev/null`
3. **lint** - `lint 2>/dev/null`. Zero errors.

Fix ALL failures, including pre-existing ones.

**If ALL GREEN** -> Pipeline complete. Output final summary.

**If FAIL** -> Enter self-fix loop:

1. Analyze failure output (which tests fail, which lint errors)
2. Fix the code:
   - **Test failures** -> fix implementation code. Tests are the contract, implementation must conform.
   - **Lint errors** -> fix whichever file has the error (test or implementation).
3. Re-run the failing verification command (not all three)
4. Repeat up to **3 times**

**Default**: assume tests are correct and fix implementation. **Exception**: if a test clearly contradicts the HLD, fix the test instead.

**If still failing after 3 retries** -> Display failure report:

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

During the pipeline, display phase transition markers:

```
▶ Phase 1: Test Cases + Implementation (parallel child agents with Codex review)...
▶ Phase 2: Verification...
```

On success:

```
## Auto-TDD Complete

**Requirement**: [one-line summary]
**Files created/modified**: [list]
**Tests**: [N passed, 0 failed]
**Lint**: clean
**Procedure**: {procedure_dir}/
```

---

## Batch Mode

Process multiple requirements sequentially, each in an isolated child agent.

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

The main session acts as a **dispatcher** - it runs `understand-0` for each requirement, then delegates the auto-tdd pipeline to a child agent.

For each requirement:
1. Invoke `understand-0` skill, passing the requirement name and description.
   - Bypass user-selection gates and proceed automatically.
   - Do NOT bypass critical ambiguity STOPs - fail this requirement if critical ambiguity is encountered.
2. Dispatch a child agent with the procedure directory path and instruction to execute auto-tdd.
3. Wait for child agent to complete.
4. Collect result: pass or fail.
5. Display one-line status.
6. Proceed to next requirement regardless of pass/fail.

### Batch Output

During execution:

```
▶ [1/3] add-share-button - running...
✅ [1/3] add-share-button - passed (12 tests, 0 failures)
▶ [2/3] fix-login-redirect - running...
❌ [2/3] fix-login-redirect - failed (Phase 2: vitest 2 failures)
▶ [3/3] update-user-profile - running...
✅ [3/3] update-user-profile - passed (8 tests, 0 failures)
```

After all requirements complete:

```
## Auto-TDD Batch Complete

| # | Requirement | Status | Tests | Procedure |
|---|-------------|--------|-------|-----------|
| 1 | add-share-button | PASS | 12 passed | .procedure/.../ |
| 2 | fix-login-redirect | FAIL | Phase 2 | .procedure/.../ |
| 3 | update-user-profile | PASS | 8 passed | .procedure/.../ |
```

---

## Rules

1. **Parallel child agents** - tests and implementation are written by separate Codex child agents simultaneously
2. **Codex reviews, Codex writes** - Codex adversarial-reviews each child agent's output; Codex fixes issues
3. **No human intervention** - zero confirmation gates in the pipeline
4. **Failure stops the pipeline** - do not proceed past a failed phase
5. **Implementation conforms to tests** - in Phase 2, default to fixing implementation. Fix tests only when they clearly contradict the HLD
