---
name: understand
description: Use when any code modification task is received, before design or implementation. Structures requirement analysis and HLD design via a subagent.
---

# Requirements Understanding

Structured requirement analysis + HLD design via a single subagent. Output is written to a procedure directory for full traceability. Must complete before any implementation.

## When to Use

Any task involving code changes: new features, bug fixes, refactoring.

## When NOT to Use

- Pure information queries (no code changes)
- Reading/exploring codebase
- Explaining existing code
- Configuration-only changes (no code logic), unless user explicitly requests analysis
- User explicitly instructs to skip analysis and code directly

## Process

### Step 0: Initialize Procedure Directory

1. Determine the project root (git root, or current working directory if not a git repo)
2. Generate a short name (≤10 characters) summarizing the user's requirement
3. Create directory: `{project_root}/.claude/procedure/{YYYY-MM-DD}/{name}/`
4. Write `requirement.md` to the procedure directory:
   - The user's chat message (verbatim)
   - If the message references an external spec/requirement file (e.g., a PRD, feature spec, or any document containing detailed requirements): read that file and append its full content after the user's message, preceded by a `## Source Spec` heading
5. Store the procedure directory path — all subsequent steps reference it as `{procedure_dir}`

### Step 1: Dispatch Subagent

Launch an Agent subagent (general-purpose) with `name: "understand-agent"` to execute the analysis and design phases. This isolates exploration noise (CodeGraph, CocoIndex, LSP calls) from the main session.

**Subagent prompt must contain only:**
1. The procedure directory path
2. Instruction: "First, invoke the `my-explore` skill using the Skill tool to load code navigation methodology."
3. Instruction to read `~/.claude/skills/understand/subagent-instructions.md` and follow it exactly
4. Instruction: "Do NOT invoke the `understand` skill via the Skill tool — you are already executing it by following subagent-instructions.md directly."

**Do NOT add** file paths, component names, implementation guidance, or any context beyond the procedure directory path. The subagent reads `requirement.md` and discovers project structure on its own. Adding implementation-ready information causes the subagent to skip analysis and jump to solutions.

### Metrics Recording (after every agent call or SendMessage resume)

After every Agent dispatch or SendMessage resume returns, extract the `<usage>` block (total_tokens, tool_uses, duration_ms) and append a row to `{procedure_dir}/metrics.md`:

```markdown
# Agent Metrics

| Phase | Tokens | Tool Uses | Duration | Timestamp |
|-------|--------|-----------|----------|-----------|
| [brief description of what the agent did] | [total_tokens] | [tool_uses] | [duration formatted as Xm Ys] | [ISO 8601 timestamp] |
```

Create the file with header on first write; append rows on subsequent writes. This applies to ALL agent calls and SendMessage resumes in this skill.

### Step 2: Handle Result

**Save the understand agent ID immediately** — the Agent tool returns an agent ID (e.g., `agentId: a1b2c3d4`). Save it as `understand_agent_id` BEFORE checking the status — you need it for NEEDS_CLARIFICATION, ISSUES_FOUND fixes, and user-requested changes. This is the ONLY agent you will resume directly. The self-check skill manages its own reviewer agent internally.

Parse the subagent's returned output for `STATUS`:

#### STATUS: COMPLETE

The subagent wrote output files to the procedure directory. Check the `COMPLEXITY` field:

- **`COMPLEXITY: no-logic`** → `understand.md` written. Go to Step 2b (Review).
- **`COMPLEXITY: logic`** → `understand.md` and `hld.md` written. Go to Step 2b (Review).

#### STATUS: NEEDS_CLARIFICATION

The subagent encountered ambiguity and returned structured questions.

1. Present the questions to the user (include the `COMPLETED_SO_FAR` context if it helps the user understand why the question matters)
2. Wait for user answers
3. **Append the user's answers to `{procedure_dir}/requirement.md`** under a `## Clarifications` heading (create the heading on first append; subsequent clarifications append under the same heading). If the answer references an external file (e.g., a new or updated spec), read that file and append its content after the answer. This keeps requirement.md as the single source of truth for the reviewer.
4. **Resume the understand agent using SendMessage with `understand_agent_id`:**
   ```
   SendMessage(to: "<understand_agent_id>", message: "User answered: <user's answers>")
   ```
   IMPORTANT: Use the **agent ID** (not the agent name). SendMessage with name only delivers to inbox; SendMessage with ID actually resumes the agent with full context preserved. Do NOT launch a new Agent (loses context).
5. Parse the resumed subagent's output again — repeat until STATUS: COMPLETE.

### Step 2b: Independent Review

Invoke the `self-check` skill **using the Skill tool**, passing these parameters:
- `rules_path`: `~/.claude/skills/understand/self-check.rules.md`
- `files`: `{procedure_dir}/requirement.md, {procedure_dir}/understand.md, {procedure_dir}/hld.md`
- `output_path`: `{procedure_dir}/audit/self-check.md`

**Handle result:**

#### STATUS: PASS
All tables clean. Go to Step 3.

#### STATUS: ISSUES_FOUND
The reviewer found defects. Fix them:
1. **Resume the understand agent** using `SendMessage(to: "<understand_agent_id>", message: "Reviewer found these issues: <list issues>. Fix understand.md and/or hld.md.")`
2. After fixes, **re-invoke the `self-check` skill** with the same parameters.
3. Repeat until STATUS: PASS

### Step 3: Present Results to User

Output the procedure file paths as clickable links. **Do NOT read the file contents into the main session context** — the user opens and reviews them directly in their editor.

For logic changes:

> Analysis and design complete:
> - `{procedure_dir}/understand.md`
> - `{procedure_dir}/hld.md`
>
> Select next step:
> 1. **code** — Confirmed. Proceed to implementation.
> 2. **testcase** — Confirmed. Generate test cases first, then implement.

For no-logic changes:

> Analysis complete:
> - `{procedure_dir}/understand.md`
>
> Select next step:
> 1. **code** — Confirmed. Proceed to implementation.
> 2. **testcase** — Confirmed. Generate test cases first, then implement.

Wait for user selection:

- User replies `code` (or equivalent: "确认", "ok", "没问题", "直接编码", "proceed") → invoke the `code` skill **using the Skill tool**, passing the procedure directory path as argument.
- User replies `testcase` (or equivalent: "测试", "先写测试", "tdd") → invoke the `testcase` skill **using the Skill tool**, passing the procedure directory path as argument.

**Do NOT execute skill logic inline.** Each skill has its own mandatory process (loading standards, checklists, traceability). Skipping the Skill tool invocation bypasses those checks.

Do NOT proceed without a user selection. If the user requests changes to the analysis or design instead of selecting an option:
- **Textual changes** (rewording ACs, adjusting scope description, adding/removing affected files): **append the user's feedback to `{procedure_dir}/requirement.md`** under `## Clarifications` (if the feedback references an external file, read and append its content too), then resume the subagent using `SendMessage(to: "<understand_agent_id>", message: "<user's feedback>")`. After changes, re-present with the same options.
- **Changes requiring re-analysis** (different approach, new scope, re-examine code): **append the user's feedback to `{procedure_dir}/requirement.md`** under `## Clarifications` (if the feedback references an external file, read and append its content too), then resume the subagent using `SendMessage(to: "<understand_agent_id>", message: "<user's feedback>")` and parse its output again per Step 2.

