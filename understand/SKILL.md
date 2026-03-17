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

Launch an Agent subagent (general-purpose) to execute the analysis and design phases. This isolates exploration noise (CodeGraph, CocoIndex, LSP calls) from the main session.

**Subagent prompt must contain only:**
1. The procedure directory path
2. Instruction: "First, invoke the `my-explore` skill using the Skill tool to load code navigation methodology."
3. Instruction to read `~/.claude/skills/understand/subagent-instructions.md` and follow it exactly
4. Instruction: "Do NOT invoke the `understand` skill via the Skill tool — you are already executing it by following subagent-instructions.md directly."

**Do NOT add** file paths, component names, implementation guidance, or any context beyond the procedure directory path. The subagent reads `requirement.md` and discovers project structure on its own. Adding implementation-ready information causes the subagent to skip analysis and jump to solutions.

### Step 2: Handle Result

Parse the subagent's returned output for `STATUS`:

#### STATUS: COMPLETE

The subagent wrote output files to the procedure directory. Check the `COMPLEXITY` field:

- **`COMPLEXITY: no-logic`** → `understand.md` written. Go to Step 3.
- **`COMPLEXITY: logic`** → `understand.md` and `hld.md` written. Go to Step 3.

#### STATUS: NEEDS_CLARIFICATION

The subagent encountered ambiguity and returned structured questions.

1. Present the questions to the user (include the `COMPLETED_SO_FAR` context if it helps the user understand why the question matters)
2. Wait for user answers
3. **Resume** the same subagent (using the Agent tool's `resume` parameter) with the user's answers. The subagent retains its full context and continues analysis from where it stopped.
4. Parse the resumed subagent's output again — repeat Step 2 until STATUS: COMPLETE.

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
> 3. **audit** — Run Codex third-party audit before proceeding.

For no-logic changes:

> Analysis complete:
> - `{procedure_dir}/understand.md`
>
> Select next step:
> 1. **code** — Confirmed. Proceed to implementation.
> 2. **testcase** — Confirmed. Generate test cases first, then implement.

Wait for user selection:

- User replies `code` (or equivalent: "确认", "ok", "没问题", "直接编码", "proceed") → invoke the `code` skill **using the Skill tool**, passing the procedure directory path as argument.
- User replies `testcase` (or equivalent: "测试", "先写测试", "tdd") → proceed to Step 4.
- User replies `audit` (or equivalent: "审计", "review", "check") → invoke the `understand-hld-check` skill **using the Skill tool**. After audit completes, re-present with the same options.

**Do NOT execute skill logic inline.** Each skill has its own mandatory process (loading standards, checklists, traceability). Skipping the Skill tool invocation bypasses those checks.

Do NOT proceed without a user selection. If the user requests changes to the analysis or design instead of selecting an option:
- **Textual changes** (rewording ACs, adjusting scope description, adding/removing affected files): resume the subagent with the user's feedback. After changes, re-present with the same options.
- **Changes requiring re-analysis** (different approach, new scope, re-examine code): resume the subagent with the user's feedback and parse its output again per Step 2.

### Step 4: Testcase Subagent (when user selects testcase)

Launch an Agent subagent (general-purpose) to write test cases. This isolates test design from the main session.

**Subagent prompt must contain:**
1. The procedure directory path
2. Instruction: "First, invoke the `my-explore` skill using the Skill tool to load code navigation methodology."
3. Instruction: "Read `~/.claude/skills/testcase/SKILL.md` and follow it exactly. Read the analysis from `{procedure_dir}/understand.md`. If `{procedure_dir}/hld.md` exists, also read it for design contracts. Do NOT read `requirement.md` — the understand and HLD outputs are your sole inputs. Write the test plan to `{procedure_dir}/testcase/plan.md`. Do NOT invoke any skills via the Skill tool other than `my-explore` — you are already executing the testcase workflow by reading SKILL.md directly. At any STOP gate (test type recommendation, direction selection, AC gap check, or test plan confirmation), return with `STATUS: NEEDS_CONFIRMATION` and include the recommendation or question content so the main session can present it to the user. After test code is written and lint-clean, return with `STATUS: COMPLETE`. Do NOT invoke the `code` skill — return to the main session instead."

**Do NOT add** implementation hints or test code suggestions. The subagent derives everything from the procedure files.

**Handle subagent result:**

#### STATUS: NEEDS_CONFIRMATION

The subagent reached a STOP gate (test type recommendation, direction selection, AC gap check, or test plan confirmation).

1. Present the subagent's content to the user
2. Wait for user response
3. **Resume** the same subagent **(using the Agent tool's `resume` parameter with the subagent's agent ID)** with the user's response. Do NOT use SendMessage — SendMessage is for running agents only and will silently fail on a completed agent. The Agent tool's `resume` parameter re-launches the agent with its full previous context preserved.
4. Parse the resumed subagent's output again — repeat until STATUS: COMPLETE

#### STATUS: COMPLETE

The subagent has written all test files and completed lint verification. Re-present the procedure file links to the user with the remaining options:

> Test cases written. Select next step:
> 1. **code** — Proceed to implementation.

Wait for user confirmation before invoking the `code` skill.
