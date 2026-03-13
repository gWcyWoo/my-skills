---
name: understand-hld-check
description: Unified third-party audit of understand + HLD output before user confirmation. Dispatches Codex via subagent to keep main session context clean, then self-iterates fixes until zero issues.
---

# Understand + HLD Third-Party Audit

Independent Codex audit of the combined understand + HLD output, invoked when the user requests it after reviewing the combined output. This is the highest-leverage quality gate — errors here cascade to testcase, code, and all downstream artifacts.

**Execution model**: The audit runs in a **subagent** to avoid polluting the main session's context with the audit prompt, serialized artifacts, and Codex response. Only the audit result (PASS or violation list) returns to the main session.

## When to Use

Invoked from `understand` Step 3c when the user requests a third-party audit. This is **user-initiated**, not automatic — the `understand` skill presents the combined output first and asks the user whether to run this audit.

## Process

### Step 1: Prepare Inputs (main session)

Collect from the current conversation:

1. **User's Original Request** — The raw task description/spec from the user
2. **Requirements Analysis** — The `understand` Step 2 output (task type, analysis, affected files, acceptance criteria)
3. **HLD Design** — The `hld` output (interfaces, signatures, module boundaries, interaction flow, design decisions)
4. **CLAUDE.md path** — The project's CLAUDE.md file path for architecture rules

### Step 2: Dispatch Subagent (main session)

Launch an Agent subagent with the following instructions:

1. Read the audit prompt template from `~/.claude/skills/understand-hld-check/audit-prompt.md`
2. Read the architectural rules from the CLAUDE.md path
3. Construct the Codex prompt by substituting the four inputs into the template's placeholder sections
4. Invoke the `codex` skill with the constructed prompt. When executing the Codex Bash command, set `timeout: 600000` (10 minutes) on the Bash tool call
5. Return the Codex output verbatim — do NOT interpret, summarize, or filter. If the command times out (exit code 124), return "CODEX_TIMEOUT" as the result

**Subagent prompt must include**: All four inputs from Step 1 serialized as text, plus the CLAUDE.md path. Pass every input VERBATIM — do NOT summarize, compress, or strip type information. The codex skill requires the exact content to audit; missing details cause false positives.

### Step 3: Process Result (main session)

Parse the subagent's returned Codex output for **Status** and **Violations**.

- **"STATUS: 100% COMPLIANT"** → Go to Step 5
- **Violations found** → Go to Step 4

### Step 4: Fix-and-Self-Review Loop (main session)

For each violation reported by Codex:

1. **Determine fix location** — Is the issue in Requirements Analysis or HLD Design?
   - AC completeness / scope issues → fix Requirements Analysis
   - Module / interface / flow issues → fix HLD Design
   - Traceability issues → may require fixing both
2. **Apply the fix** — Modify the affected artifact according to the suggested fix
3. **Scoped self-review** — ONLY verify that each reported violation has been correctly fixed. Do NOT expand audit scope.
   - For each violation ID: Is the fix applied? Does it resolve the issue without introducing a new violation of the SAME category?
   - **Scope boundary**: If a fix is correct, move on. Do not re-audit unrelated parts.
4. **If a fix introduces a new issue** — Fix that specific regression and re-verify it only
5. **If all fixes verified** → Go to Step 5

**Self-review rules:**
- Review ONLY the changed portions — not the entire document
- Check ONLY whether each Codex-reported violation is resolved
- Do NOT flag new issues that Codex did not report
- Output a simple checklist: `[violation ID] — Fixed: Y/N`

### Step 5: Return to Understand (main session)

Once zero issues confirmed, return the audited output to the `understand` flow. The `understand` skill will re-present the updated combined output to the user in Step 3c.

## Decision Summary

```
Main session: Prepare inputs → Dispatch subagent
Subagent: Read audit prompt → Read rules → Construct Codex prompt → Run Codex → Return result
Main session: Parse result → PASS? → Return to understand Step 3c
                           → FAIL? → Fix artifacts → Self-review → Return to understand Step 3c
```

**Do NOT return artifacts with known unfixed violations to the understand flow.**
