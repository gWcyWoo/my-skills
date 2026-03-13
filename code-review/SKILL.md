---
name: code-review
description: Use when code review is needed after implementation. Supports multiple reviewers (codex, claude) and loads project-specific review standards.
---

# Code Review

Dispatch a code review on implemented code. Supports multiple reviewers and project-specific standards.

## Step 1: Gather Review Context

Identify TWO inputs before proceeding:

### 1a. Review Baseline

Search the current conversation for what the code should be reviewed against, in priority order:

1. **HLD design** — interfaces, function signatures, module boundaries
2. **Requirements analysis** (`understand` skill output) — acceptance criteria, scope
3. **User's original request** — the task description that initiated the implementation

Use the highest-priority item found. If multiple exist, use all of them.

If NONE exist in conversation, ask the user and STOP:

> No review baseline found. What should I review this code against? Please describe the requirements or goals.

### 1b. Code to Review

Identify the files to review using ONE of these methods (in priority order):

1. Files the user explicitly specified (e.g. `/code-review src/foo.ts`)
2. Files modified in the current conversation (tracked by tool calls: Write, Edit)
3. If neither is available, run `git diff --name-only HEAD` to get recently changed files

If no files can be identified, ask the user and STOP:

> Which files should I review?

**Output both the review baseline summary and the file list to the user before proceeding.**

---

## Step 2: Select Reviewer

Check if the user passed a reviewer argument: `/code-review codex` or `/code-review claude`.

If no argument was provided, ask and STOP:

> Which reviewer should I use?
> 1. **codex** — L7 Zero-Trust audit via Codex CLI
> 2. **claude** — Claude Code subagent review

**Do NOT proceed until the user responds.** Do not infer a reviewer from conversation history or any other signal.

---

## Step 3: Load & Extract Review Checklist

### 3a. Load Standards Files

Determine project type by checking `package.json` dependencies and file extensions of the files to review. Load all matching standards files. Skip any file already in conversation context.

| Condition | File to Read |
|---|---|
| TypeScript (`.ts`/`.tsx` files) | `~/.claude/shared-rules/common/typescript.md` |
| Any frontend (`.vue`/`.tsx`/`.jsx` files) | `~/.claude/shared-rules/frontend/architecture.md` |
| Vue (`vue` in dependencies) | `~/.claude/shared-rules/frontend/vue3.md` |
| React (`react` in dependencies) | `~/.claude/shared-rules/frontend/reactjs.md` |
| Next.js (`next` in dependencies) | `~/.claude/shared-rules/frontend/nextjs.md` |
| Any backend (non-frontend `.ts`/`.js` files) | `~/.claude/shared-rules/backend/ddd.md` |
| Express (`express` in dependencies) | `~/.claude/shared-rules/backend/express.md` |
| MongoDB (`mongoose`/`mongodb` in dependencies) | `~/.claude/shared-rules/backend/mongodb.md` |

### 3b. Extract Review Checklist

From each loaded standards file, extract every rule that can be checked as YES/NO against code. Compile into a single checklist with source attribution:

```
Review Checklist:
- [ ] No `any` types (source: typescript.md)
- [ ] Components follow single-responsibility (source: architecture.md)
- [ ] State management uses composables, not global mutable state (source: vue3.md)
```

---

## Step 4: Execute Review

### Path A: Codex Reviewer

1. Read `~/.claude/skills/code/code-implementation-audit-prompt.md`. If not found, search with Glob (`**/code-implementation*`). If still not found, STOP and inform the user.
2. Construct a single prompt string containing: audit template + review baseline + review checklist + full source code of each file to review.
3. Invoke `codex` skill with this prompt string.

### Path B: Claude Reviewer

1. Read the source code of all files to review.
2. Dispatch a `superpowers:code-reviewer` or `everything-claude-code:code-reviewer` subagent (use Agent tool with the appropriate `subagent_type`). In the agent prompt, include:
   - The review baseline (requirements/HLD/goals)
   - The review checklist (from Step 3b)
   - The full source code of each file
   - Instruction: "Review this code against the baseline and checklist. Report all violations. Do not fix anything."

---

## Step 5: Output Review Report

Present the reviewer's findings to the user in this format:

```
## Review Report

**Reviewer:** [codex / claude]
**Files Reviewed:** [file list]
**Baseline:** [one-line summary of what was reviewed against]

### Violations

| # | File | Line | Rule Violated | Description | Severity |
|---|------|------|---------------|-------------|----------|
| 1 | src/foo.ts | 42 | No `any` types | `param: any` used | High |

### Summary
- Total violations: N
- High: N / Medium: N / Low: N
```

Do NOT fix any violations. The user decides next steps.
