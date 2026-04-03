---
name: understand
description: Use when a code-change request needs structured requirements analysis before implementation, TDD, or auto-tdd, especially when HLD or persisted procedure files may be needed.
---

# Requirements Understanding

Analyze requirements in the main session with the user in the loop. Auto-invokes brainstorming when the requirement is complex or ambiguous. Files (`requirement.md`, `understand.md`, `hld.md`) are written only when the user requests persistence.

## When to Use

Any task involving code changes: new features, bug fixes, refactoring.

## When NOT to Use

- Pure information queries (no code changes)
- Reading/exploring codebase
- Explaining existing code
- Configuration-only changes (no code logic), unless user explicitly requests analysis
- User explicitly instructs to skip analysis

## Code Navigation Rule

**The `my-explore` skill is the ONLY permitted code navigation methodology.** This applies at ALL times - including when the brainstorming skill is active. Brainstorming explores *requirements and ideas*; `my-explore` explores *code*. Never use any other approach for code navigation, regardless of what other loaded skills suggest.

`understand` does not define, refine, or override any code-exploration tool choice, tool sequence, fallback rule, or shell rule. All code-exploration tool usage is delegated to `my-explore`.

## Process

### Step 1: Explore & Analyze

1. Invoke the `my-explore` skill. From that point forward, all code-exploration tool usage is governed by `my-explore`, not by `understand`.

2. Follow `/Users/Woo/.agents/skills/understand/analysis-instructions.md` for the analysis process (classification, analysis, AC extraction, complexity gate). **The user's conversation message is the requirement input - ignore any `requirement.md` file references. Present the analysis in conversation - do NOT write files yet.**

   During analysis, if anything is ambiguous:
   - Non-critical -> record the ambiguity and continue
   - Critical -> **STOP and ask the user**

   **Brainstorming trigger**: During analysis, if you encounter any of the following, invoke the `brainstorming` skill using the Skill tool - do NOT ask the user first:
   - Multiple valid design approaches with no clear winner
   - Requirement scope is vague or open-ended
   - Significant trade-offs that need exploration (performance vs complexity, UX vs implementation cost)
   - The requirement touches multiple systems with unclear boundaries

   **Code exploration during brainstorming MUST use `my-explore` only - no other navigation approach.** `understand` still does not add any tool-level rules here. After brainstorming completes, continue the analysis with the refined understanding.

3. For logic changes, follow `/Users/Woo/.agents/skills/hld/SKILL.md` Steps 0-3 for HLD design (load rules, AC-driven scope, design, author check). **Use the analysis from step 2 in place of `understand.md` file reads. Present the HLD in conversation - do NOT write files yet.**

4. **STOP and present** the complete understanding to the user:
   - Summary, task type, affected files, acceptance criteria
   - For logic changes: HLD (interfaces, module boundaries, interaction flows)
   - Wait for user to confirm, correct, or request changes
   - Do NOT proceed until the user confirms

### Step 2: Persistence Decision

After the user confirms the understanding, **STOP and ask**:

> Do you want to persist the analysis to a procedure directory? (Required for auto-tdd. Small changes can skip this.)

- If **no** -> skip to Step 3. No files are written.
- If **yes**:
  1. Create directory: `{project_root}/.procedure/{YYYY-MM-DD}/codex_{name}/` (name <=10 chars, project_root = git root or cwd)
  2. Write `requirement.md` - the user's original request (verbatim). If it references an external spec, append under `## Source Spec`. Include any clarifications from conversation under `## Clarifications`.
  3. Write `understand.md` - the requirements analysis.
  4. Write `hld.md` - HLD design (logic changes only).
  5. **Adversarial review** - run `/codex:adversarial-review --wait {procedure_dir}/requirement.md {procedure_dir}/understand.md {procedure_dir}/hld.md` to challenge the analysis and design.

     Handle the review result:
     - **No issues** -> proceed to step 6.
     - **Issues found** -> fix the affected files, then re-run the adversarial review. Repeat up to **2 times**. If issues persist after 2 rounds, present remaining issues to the user for decision.

  6. Output file paths as clickable links. **Do NOT read the file contents back into conversation** - the user reviews them directly in their editor.

### Step 3: Next Steps

> Select next step:
> 1. **code** - Implement directly (Codex).
> 2. **tdd** - Lightweight TDD: user stays in the loop for test design and implementation.
> 3. **auto-tdd** - Automated: test generation and code implementation run in parallel. (Requires persisted files)

- `code` (or equivalent user intent to proceed with direct implementation) -> Codex implements directly, following the HLD and project standards. Uses conversation context if files were not persisted.
- `tdd` (or equivalent user intent to start with tests) -> invoke the `tdd` skill using the Skill tool. Lightweight flow with user in the loop.
- `auto-tdd` (or equivalent user intent to run the automated parallel workflow) -> invoke the `auto-tdd` skill using the Skill tool, passing the procedure directory path. **Requires files to be persisted in Step 2.** If not persisted, ask the user to persist first.

Wait for user selection. **Do NOT proceed without it.**

If the user requests changes instead of selecting:
- Re-analyze the affected parts, re-present, and ask again.
- If files were persisted, update them accordingly.
