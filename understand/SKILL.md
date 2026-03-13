---
name: understand
description: Use when any code modification task is received, before design or implementation. Structures requirement analysis and HLD design in one pass.
---

# Requirements Understanding

Structured requirement analysis + HLD design. Must complete before any implementation.

## When to Use

Any task involving code changes: new features, bug fixes, refactoring.

## When NOT to Use

- Pure information queries (no code changes)
- Reading/exploring codebase
- Explaining existing code
- Configuration-only changes (no code logic), unless user explicitly requests analysis
- User explicitly instructs to skip analysis and code directly

## Process

### Step 1: Dispatch Analysis Subagent

Launch an Agent subagent (general-purpose) to execute the full analysis phase. This isolates exploration noise (file reads, LSP calls, self-check evidence) from the main session, preserving attention for subsequent phases.

**Subagent prompt must contain only:**
1. The user's original request (verbatim)
2. Instruction to read `~/.claude/skills/understand/subagent-instructions.md` and follow it exactly
3. Instruction: "Do NOT invoke the `understand` skill via the Skill tool — you are already executing it by following subagent-instructions.md directly. You MAY invoke other skills (e.g., `hld`) as instructed by subagent-instructions.md."

**Do NOT add** file paths, component names, implementation guidance, or any context beyond the user's original words. The subagent discovers project structure on its own. Adding implementation-ready information causes the subagent to skip analysis and jump to coding.

### Step 2: Handle Subagent Result

Parse the subagent's returned output for `STATUS`:

#### STATUS: COMPLETE

The subagent returned the combined document. Go to Step 3.

#### STATUS: NEEDS_CLARIFICATION

The subagent encountered ambiguity and returned structured questions.

1. Present the questions to the user (include the `COMPLETED_SO_FAR` context if it helps the user understand why the question matters)
2. Wait for user answers
3. **Resume** the same subagent (using the Agent tool's `resume` parameter) with the user's answers. The subagent retains its full context and continues analysis from where it stopped.
4. Parse the resumed subagent's output again — repeat Step 2 until `STATUS: COMPLETE`.

### Step 3: Present Combined Output

Strip the `STATUS: COMPLETE` prefix from the subagent's output. Present the remaining combined document to the user and ask:

> **Select next step:**
> 1. **code** — Confirmed. Proceed to implementation.
> 2. **testcase** — Confirmed. Generate test cases first, then implement.
> 3. **audit** — Run third-party audit (`understand-hld-check`) before proceeding.
> 4. **save** — Save HLD record to `.auto-tdd/` for quality analysis.

- User replies `1` / `code` (or equivalent: "确认", "ok", "没问题", "直接编码", "proceed") → invoke the `code` skill **using the Skill tool**.
- User replies `2` / `testcase` (or equivalent: "测试", "先写测试", "tdd") → proceed to Step 4.
- User replies `3` / `audit` (or equivalent: "审计", "review", "check") → invoke the `understand-hld-check` skill **using the Skill tool**. If violations are found, fix them per the skill's instructions, then re-present the updated output to the user with the same four options.
- User replies `4` / `save` (or equivalent: "保存", "记录", "save hld") → invoke the `save-hld-record` skill **using the Skill tool**. After saving, re-present the same four options so the user can continue.

**Do NOT execute skill logic inline.** Each skill has its own mandatory process (loading standards, checklists, traceability). Skipping the Skill tool invocation bypasses those checks.

Do NOT proceed without a user selection. If the user requests changes to the analysis or design instead of selecting an option:
- **Textual changes** (rewording ACs, adjusting scope description, adding/removing affected files): apply directly to the document and re-present with the same four options.
- **Changes requiring re-analysis** (different approach, new scope, re-examine code): resume the subagent with the user's feedback and parse its output again per Step 2.

### Step 4: Testcase Subagent (when user selects testcase)

Launch an Agent subagent (general-purpose) to write test cases. This isolates test design and code generation from the main session, keeping context clean for the subsequent `code` phase.

**Subagent prompt must contain:**
1. The confirmed combined document (Requirements Analysis + HLD) from Step 3
2. Instruction: "Read `~/.claude/skills/testcase/SKILL.md` and follow it exactly. Do NOT invoke any skills via the Skill tool — you are already executing the testcase workflow by reading SKILL.md directly. At the STOP gate in Step 0 (test type recommendation) or Step 1 (test plan), return your output with `STATUS: NEEDS_CONFIRMATION` at the top. After Step 2 is complete (test code written and lint-clean), return with `STATUS: COMPLETE`. Do NOT invoke the `code` skill — return to the main session instead."

**Do NOT add** implementation hints or test code suggestions. The subagent derives everything from the HLD.

**Handle subagent result:**

#### STATUS: NEEDS_CONFIRMATION

The subagent reached a STOP gate in Step 0 (test type recommendation) or Step 1 (test plan).

1. Present the subagent's content to the user
2. Wait for user response
3. Resume the subagent with the user's response
4. Parse the resumed result — repeat until STATUS: COMPLETE

#### STATUS: COMPLETE

The subagent has written all test files and completed lint verification. Invoke the `code` skill **using the Skill tool** to begin implementation.
