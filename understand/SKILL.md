---
name: understand
description: Requirement analysis and HLD design in the main session. Produces understand.md + hld.md in a procedure directory. Run before auto-tdd or manual implementation.
---

# Requirements Understanding

Requirement analysis + HLD design running in the main session. Output is written to a procedure directory for full traceability. Must complete before any implementation.

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
3. Create directory: `{project_root}/.procedure/{YYYY-MM-DD}/claude_{name}/`
4. Write `requirement.md` to the procedure directory:
   - The user's chat message (verbatim)
   - If the message references an external spec/requirement file (e.g., a PRD, feature spec, or any document containing detailed requirements): read that file and append its full content after the user's message, preceded by a `## Source Spec` heading
5. Store the procedure directory path — all subsequent steps reference it as `{procedure_dir}`

### Step 1: Analyze

Invoke the `my-explore` skill to load code navigation methodology. Then read `~/.claude/skills/understand/analysis-instructions.md` and follow it to analyze the requirement and produce output files.

During analysis, if anything is ambiguous:
- If the analysis can continue meaningfully → record the ambiguity and continue
- If the ambiguity is critical → **STOP and ask the user**. After the user answers, append the answers to `{procedure_dir}/requirement.md` under a `## Clarifications` heading, then continue the analysis.

Write output to the procedure directory:
- `understand.md` — requirements analysis (always)
- `hld.md` — high-level design contracts (for logic changes only)

### Step 2: Present Results to User

Output the procedure file paths as clickable links. **Do NOT read the file contents into the main session context** — the user opens and reviews them directly in their editor.

For logic changes:

> Analysis and design complete:
> - `{procedure_dir}/understand.md`
> - `{procedure_dir}/hld.md`
>
> Select next step:
> 1. **code** — Implement only.
> 2. **testcase** — Generate test cases only.
> 3. **both** — Run testcase and code in parallel.

For no-logic changes:

> Analysis complete:
> - `{procedure_dir}/understand.md`
>
> Select next step:
> 1. **code** — Implement only.
> 2. **testcase** — Generate test cases only.
> 3. **both** — Run testcase and code in parallel.

Wait for user selection:

- User replies `code` (or equivalent: "确认", "ok", "没问题", "直接编码", "proceed") → invoke the `auto-code` skill **using the Skill tool**, passing the procedure directory path as argument.
- User replies `testcase` (or equivalent: "测试", "先写测试") → invoke the `auto-testcase` skill **using the Skill tool**, passing the procedure directory path as argument.
- User replies `both` (or equivalent: "并行", "都跑", "tdd", "all") → invoke **both** the `auto-testcase` and `auto-code` skills in parallel, each using the Skill tool, each passing the procedure directory path as argument. Both skills derive from the same HLD and have no data dependency on each other.

**Do NOT execute skill logic inline.** Each skill has its own mandatory process (loading standards, checklists, traceability). Skipping the Skill tool invocation bypasses those checks.

Do NOT proceed without a user selection. If the user requests changes to the analysis or design instead of selecting an option:
- **Textual changes** (rewording ACs, adjusting scope description, adding/removing affected files): append the user's feedback to `{procedure_dir}/requirement.md` under `## Clarifications`, then re-run the relevant part of the analysis. After changes, re-present with the same options.
- **Changes requiring re-analysis** (different approach, new scope, re-examine code): append the user's feedback to `{procedure_dir}/requirement.md` under `## Clarifications`, then re-run the analysis from Step 1 and present results again.
