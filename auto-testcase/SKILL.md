---
name: auto-testcase
description: Use when writing test cases. Dispatches subagent to auto-recommend test types, design test plan, and write test code. Runs straight through with no user gates.
---

# Testcase Orchestration

Dispatches a testcase subagent that runs straight through (no STOP gates, no user confirmation). Isolates test design from the main session.

## Parameters

The caller must provide:
- `procedure_dir` — the procedure directory path (containing `hld.md`)

## Process

### Step 1: Dispatch Subagent

Launch an Agent subagent (general-purpose) with `name: "testcase-agent"` and this prompt:
1. The procedure directory path
2. Instruction: "First, invoke the `my-explore` skill using the Skill tool to load code navigation methodology."
3. Instruction: "Read `~/.claude/skills/auto-testcase/subagent-instructions.md` and follow it exactly. Do NOT invoke any skills via the Skill tool other than `my-explore` — you are already executing the testcase workflow by reading subagent-instructions.md directly. **SKIP ALL STOP GATES** — do NOT return STATUS: NEEDS_CONFIRMATION at any point. Auto-accept all recommendations, directions, and test plans. Run straight through from Step 0 to Step 2 (write tests + self-check) and return STATUS: COMPLETE."

**Do NOT add** implementation hints, test code suggestions, or any context beyond the procedure directory path.

### Metrics Recording

After the Agent dispatch returns, extract the `<usage>` block (total_tokens, tool_uses, duration_ms) and append a row to `{procedure_dir}/metrics.md`. Create the file with header on first write; append rows on subsequent writes.

### Step 2: Handle Result

The subagent runs straight through (no STOP gates) and returns STATUS: COMPLETE with all test files written and lint-clean. Proceed to Step 3 (Review).

### Step 3: Independent Review

For **each test type** produced by the subagent, invoke the `review` skill with the corresponding rules file:

| Test Type | Rules File | Output Path |
|-----------|-----------|-------------|
| integration | `~/.claude/skills/auto-testcase/self-check.rules.md` | `{procedure_dir}/audit/testcase-self-check.md` |
| e2e | `~/.claude/skills/auto-testcase/self-check-e2e.rules.md` | `{procedure_dir}/audit/testcase-e2e-self-check.md` |

Invoke the `review` skill **using the Skill tool** for each applicable type, passing:
- `rules_path`: the rules file for this test type (from table above)
- `files`: `{procedure_dir}/hld.md`, and the test files for this type
- `output_path`: the output path for this test type (from table above)

**Handle result:**

#### STATUS: PASS
All tables clean. Return to the caller with STATUS: COMPLETE.

#### STATUS: ISSUES_FOUND
The reviewer found issues it could not fix (requires architectural change). Present the unfixable issues to the user for escalation.
