---
name: auto-testcase
description: Claude writes test cases in a subagent, then Codex adversarial-reviews. Self-contained — writes, gets reviewed, fixes, and returns lint-clean test code.
---

# Auto-Testcase

Claude subagent writes test cases from the HLD, then Codex adversarial-reviews the test code. The subagent fixes review issues and returns lint-clean test code. Self-contained pipeline.

## Parameters

The caller must provide:
- `procedure_dir` — the procedure directory path (containing `hld.md`)

## Process

### Step 1: Dispatch Subagent

Launch an Agent subagent (general-purpose) with `name: "testcase-agent"` and the following prompt:

```
You are writing test cases for the requirement in {procedure_dir}/hld.md. Work independently from start to finish.

1. Invoke the `my-explore` skill using the Skill tool to load code navigation methodology.

2. Read {procedure_dir}/hld.md — sole design authority. Do NOT read requirement.md or understand.md.

3. Read general test rules: /Users/Woo/.claude/skills/auto-testcase/general.md

4. Determine test types by analyzing the HLD:
   - integration (multiple modules interact) → read /Users/Woo/.claude/skills/auto-testcase/integration.md
   - e2e (changes affect a web page) → read /Users/Woo/.claude/skills/auto-testcase/e2e.md
   - unit supplement (single-module ACs not covered by integration/e2e) → read /Users/Woo/.claude/skills/auto-testcase/unit.md

5. Write test code per type, following each type file's rules. Load applicable test standards:
   - All projects: /Users/Woo/.code/shared-rules/test.md
   - Vue (vue in dependencies): /Users/Woo/.code/shared-rules/vuejs.test.md
   - TypeScript (.ts/.tsx): /Users/Woo/.code/shared-rules/typescript.test.md

6. Run `lint 2>/dev/null`. Fix until zero errors.

7. Run /codex:adversarial-review --wait on the test files you wrote. Fix any issues found, re-lint. Repeat up to 2 times if issues persist.

8. Return a summary: test files created, test count per type, review status.

Code reading boundaries (TDD discipline):
- Source of truth: HLD interfaces, function signatures, module boundaries
- Allowed to read: type/interface definition files (schema.ts, types.ts, .d.ts), existing test files (for patterns only), project config
- FORBIDDEN: files containing function bodies or business logic

SKIP ALL STOP GATES — do NOT return STATUS: NEEDS_CONFIRMATION. Auto-accept all recommendations and run straight through.
```

### Step 2: Handle Result

- **Success** → return STATUS: COMPLETE to the caller.
- **Failure** → display the failure details to the user.
