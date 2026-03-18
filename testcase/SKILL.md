---
name: testcase
description: Use when writing test cases. Dispatches subagent to recommend test types, design test plan, and write test code. Handles STOP gate confirmations via resume.
---

# Testcase Orchestration

Dispatches a testcase subagent and handles user confirmations at STOP gates. This isolates test design from the main session.

## Parameters

The caller must provide:
- `procedure_dir` — the procedure directory path (containing `understand.md` and optionally `hld.md`)

## Process

### Step 1: Dispatch Subagent

Launch an Agent subagent (general-purpose) with `name: "testcase-agent"` and this prompt:
1. The procedure directory path
2. Instruction: "First, invoke the `my-explore` skill using the Skill tool to load code navigation methodology."
3. Instruction: "Read `~/.claude/skills/testcase/subagent-instructions.md` and follow it exactly. Do NOT invoke any skills via the Skill tool other than `my-explore` — you are already executing the testcase workflow by reading subagent-instructions.md directly."

**Do NOT add** implementation hints, test code suggestions, or any context beyond the procedure directory path.

### Step 2: Handle Result

**Save the testcase agent ID immediately** — the Agent tool returns an agent ID (e.g., `agentId: a1b2c3d4`). Save it as `testcase_agent_id` BEFORE checking the status. This is the ONLY agent you will resume; the self-check reviewer agent (Step 3) is disposable and never resumed.

#### STATUS: NEEDS_CONFIRMATION

The subagent reached a STOP gate (test type recommendation, direction selection, AC gap check, or test plan confirmation).

1. Present the subagent's content to the user
2. Wait for user response
3. **Resume the agent using SendMessage with `testcase_agent_id`:**
   ```
   SendMessage(to: "<testcase_agent_id>", message: "User confirmed: <user's response>")
   ```
   Example: `SendMessage(to: "a1b2c3d4", message: "User confirmed: integration tests, all 4 directions")`

   IMPORTANT: Use the **agent ID** (not the agent name). SendMessage with name only delivers to inbox; SendMessage with ID actually resumes the agent with full context preserved.

   **FORBIDDEN alternative:**
   - ~~Agent(prompt="continue writing tests...")~~ — new agent loses all previous context (wastes ~20k tokens). Always use SendMessage with agent ID to resume.

4. Parse the resumed subagent's output again — repeat until STATUS: COMPLETE.

#### STATUS: COMPLETE

The subagent has written all test files and completed lint verification. Proceed to Step 3 (Review).

### Step 3: Independent Review

Invoke the `self-check` skill **using the Skill tool**, passing these parameters:
- `procedure_dir`: the procedure directory path
- `rules_path`: `~/.claude/skills/testcase/self-check.rules.md`
- `files`: `{procedure_dir}/hld.md, {procedure_dir}/understand.md`, and all test files written by the subagent
- `output_path`: `{procedure_dir}/audit/testcase-self-check.md`

**Handle result:**

#### STATUS: PASS
All tables clean. Return to the caller with STATUS: COMPLETE.

#### STATUS: ISSUES_FOUND
The reviewer found defects. Fix them:
1. **Resume the testcase agent** (NOT the self-check reviewer) using `SendMessage(to: "<testcase_agent_id>", message: "Reviewer found these issues: <list issues>. Fix the test code.")`
2. After fixes, **re-invoke the `self-check` skill** with the same parameters to verify the fixes
3. Repeat until STATUS: PASS
