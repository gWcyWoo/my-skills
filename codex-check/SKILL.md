---
name: codex-check
description: Generic Codex CLI audit framework. Dispatches subagent to run Codex with caller-provided rules, then self-iterates fixes until zero issues. Reusable across understand, testcase, code phases.
---

# Codex Audit Framework

Generic framework for running Codex CLI audits. The caller provides:
1. **Files to audit** — the artifacts to verify
2. **Rules file** — audit template with checks and output format
3. **Output path** — where to write the audit result
4. **Coding standards detection** — whether to auto-detect and load project coding standards

This skill dispatches a subagent that runs Codex CLI, parses results, fixes violations, and verifies fixes.

## Parameters

When invoking this skill, the caller must provide:
- `procedure_dir` — the procedure directory path
- `rules_path` — absolute path to the audit rules/template file (e.g., `~/.claude/skills/understand/codex-check.rules.md`)
- `files` — list of files to audit (e.g., `understand.md, hld.md`)
- `baseline_files` — baseline files to audit against (e.g., `requirement.md`)
- `output_path` — where to write the result (e.g., `{procedure_dir}/audit/result.md`)
- `load_coding_standards` — whether to detect project type and load matching rules (default: true)

## Process

### Step 1: Dispatch Subagent

Launch an Agent subagent with the following instructions:

1. First, invoke the `my-explore` skill using the Skill tool to load code navigation methodology. Follow it for all code navigation during the fix-and-verify loop.
2. Read `~/.claude/skills/codex/SKILL.md` for the Codex CLI execution format (model, flags, timeout).
3. Construct the Codex prompt string by replacing `{rules_path}`, `{list of file paths}`, and `{list of baseline file paths}` with the actual file paths. Do NOT read file contents and inline them — Codex reads files itself via `--sandbox read-only`:

   ```
   Read the following files, then perform the audit.

   AUDIT TEMPLATE (read first — defines checks and output format):
   {rules_path}

   FILES TO AUDIT:
   {list of file paths}

   BASELINE:
   {list of baseline file paths}

   CODING STANDARDS (read package.json to detect project type, then read matching files):
   - TypeScript (.ts/.tsx) → ~/.claude/shared-rules/common/typescript.md
   - Frontend (.vue/.tsx/.jsx) → ~/.claude/shared-rules/frontend/architecture.md
   - Vue (vue in deps) → ~/.claude/shared-rules/frontend/vue3.md
   - React (react in deps) → ~/.claude/shared-rules/frontend/reactjs.md
   - Next.js (next in deps) → ~/.claude/shared-rules/frontend/nextjs.md
   - Next.js fullstack (next + db) → ~/.claude/shared-rules/frontend/nextjs-fullstack.md
   - Backend (non-frontend .ts/.js) → ~/.claude/shared-rules/backend/ddd.md
   - Express (express in deps) → ~/.claude/shared-rules/backend/express.md
   - MongoDB (mongoose/mongodb in deps) → ~/.claude/shared-rules/backend/mongodb.md

   After reading all files, fill the audit template placeholders and execute the audit checks.
   Output results in the format specified in the audit template.
   ```

   If `load_coding_standards` is false, omit the CODING STANDARDS section.

4. Execute using the format from `codex/SKILL.md`, passing this prompt string.
5. Write the Codex output to `{output_path}`.
6. Parse the Codex output for **Status**:
   - **"STATUS: 100% COMPLIANT"** → Return to main session with `STATUS: PASS`
   - **Violations found** → Proceed to Step 2 for the fix-and-verify process. Return `STATUS: FIXED` when all violations are resolved.

### Step 2: Fix-and-Verify Loop (in subagent)

This step iterates until all violations are resolved and no new issues are introduced.

#### 2a: Apply All Fixes

For each violation reported by Codex:
1. **Determine fix location** — based on the violation category, fix the appropriate file(s)
2. **Apply the fix** — Edit the affected file(s)

#### 2b: Per-Violation Verification

After all fixes are applied, verify **every single violation** with structured evidence:

```
[ID-01] CATEGORY — "description"
  Before: [quote the problematic text]
  Fix applied: [quote the new text]
  Contradiction check: search the document for the same field/term — does the fix contradict anything else?
  Verdict: FIXED or STILL_BROKEN
```

#### 2c: Convergence Check

1. Count: how many FIXED, how many STILL_BROKEN?
2. If any STILL_BROKEN → return to 2a with only the STILL_BROKEN items
3. If all FIXED → proceed to 2d

#### 2d: Regression Scan

Read the modified sections. For each modification, check:
- Does the fix introduce a new contradiction?
- Does the fix reference something not defined elsewhere?
- Does the fix break an existing contract?

If any regression → treat as new violation, return to 2a.
If no regressions → Return to main session with `STATUS: FIXED`

### Step 3: Handle Result

- **`STATUS: PASS`** — No violations. Return to caller.
- **`STATUS: FIXED`** — All violations fixed and verified. Return to caller.

**The subagent does NOT return with known unfixed violations.**
