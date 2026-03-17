---
name: understand-hld-check
description: Independent third-party audit of understand.md and hld.md. Checks requirement understanding and design quality. Dispatches subagent to run Codex CLI, then self-iterates fixes until zero issues.
---

# Understand + HLD Third-Party Audit

Independent Codex audit of both understand.md and hld.md:
- **understand.md** is audited against **requirement.md** — did the analysis correctly capture what the user wants?
- **hld.md** is audited against **coding standards** — does the design follow project rules?
- **Cross-file** — do ACs and HLD elements map 1:1?

This is the highest-leverage quality gate — errors here cascade to testcase, code, and all downstream artifacts.

**Execution model**: A single subagent handles the entire audit lifecycle — running Codex CLI, parsing results, fixing violations, and verifying fixes. The main session only dispatches and receives the final result, keeping its context clean.

## When to Use

Invoked from `understand` Step 3 when the user requests a third-party audit. This is **user-initiated**, not automatic — the `understand` skill presents the procedure file links first and asks the user whether to run this audit.

## Process

### Step 1: Dispatch Subagent (main session)

The procedure directory path is available from the `understand` skill flow.

Launch an Agent subagent with the following instructions:

1. Read `~/.claude/skills/codex/SKILL.md` for the Codex CLI execution format (model, flags, timeout).
2. Construct the Codex prompt string (substitute `{procedure_dir}` with the actual path):

   ```
   Read the following files, then perform the audit.

   AUDIT TEMPLATE (read first — defines checks and output format):
   ~/.claude/skills/understand-hld-check/audit-prompt.md

   FILES TO AUDIT:
   - {procedure_dir}/understand.md
   - {procedure_dir}/hld.md

   BASELINE (the user's original requirement):
   - {procedure_dir}/requirement.md

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

   After reading all files, fill the audit template placeholders:
   <USER_REQUEST> ← requirement.md content
   <UNDERSTAND> ← understand.md content
   <HLD> ← hld.md content
   <RULES> ← matched coding standards content

   Then execute the audit checks and output results in the format specified in audit-prompt.md.
   ```

3. Execute using the format from `codex/SKILL.md`, passing this prompt string.
4. Write the Codex output to `{procedure_dir}/audit/result.md`.
5. Parse the Codex output for **Status**:
   - **"STATUS: 100% COMPLIANT"** → Return to main session with `STATUS: PASS`
   - **Violations found** → Read `~/.claude/skills/understand-hld-check/SKILL.md` Step 2 for the fix-and-verify process. Follow it exactly. Return `STATUS: FIXED` when all violations are resolved.

### Step 2: Fix-and-Verify Loop (in subagent)

This step iterates until all violations are resolved and no new issues are introduced.

#### 2a: Apply All Fixes

For each violation reported by Codex:

1. **Determine fix location** — Which file has the issue?
   - Requirements Analysis issues (AC_MISSING, AC_OVERCLAIM, AC_CONFLICT, AC_VAGUE, AC_UNTESTABLE, FILE_PHANTOM, FILE_MISSING, IMPLICIT_MISSING) → fix `{procedure_dir}/understand.md`
   - HLD design issues (IMPL_LEAK, FLOW_SKIP, FLOW_MISSING_PATH, SIG_MISMATCH, SIG_INCOMPLETE, BOUNDARY_MISCLASS, BOUNDARY_MISSING, DATA_ORIGIN_MISSING, RULE_VIOLATION) → fix `{procedure_dir}/hld.md`
   - Cross-file issues (HLD_GAP, HLD_ORPHAN, SCOPE_CREEP) → may require fixing both files
2. **Apply the fix** — Edit the affected file(s)

#### 2b: Per-Violation Verification

After all fixes are applied, verify **every single violation** with structured evidence:

```
[ID-01] AC_MISSING — "status field semantics"
  Before: AC-08 defined status as 0=pending, 1=parsed
  Fix applied: AC-08 now lists status with (pending AMB-01) marker
  Contradiction check: search all ACs for "status" → AC-14 also references status → AC-14 updated to use same marker
  Verdict: FIXED ✓

[ID-02] SIG_MISMATCH — "language optional vs required"
  Before: UploadOptions.language optional, ParseEvent.language required
  Fix applied: removed language from both interfaces
  Contradiction check: search all Flows for "language" → F15 no longer references language
  Verdict: FIXED ✓
```

Each verification MUST include:
- **Before**: What the issue was (quote the problematic text)
- **Fix applied**: What changed (quote the new text)
- **Contradiction check**: Search the rest of the document for the same field/term/concept — does the fix contradict anything else?
- **Verdict**: FIXED or STILL_BROKEN

#### 2c: Convergence Check

After all violations are verified:

1. Count results: how many FIXED, how many STILL_BROKEN?
2. If any STILL_BROKEN → return to 2a with only the STILL_BROKEN items
3. If all FIXED → proceed to 2d

#### 2d: Regression Scan

Read the modified sections of both files. For each modification, check:
- Does the fix introduce a new contradiction with any other AC, Interface, or Flow?
- Does the fix reference a field or state that is not defined elsewhere in the document?
- Does the fix break an existing Flow's Input/Output contract?

Output a structured scan:
```
Fix for ID-01 (AC-08 status) → checked against: AC-14, IResume.status, F10, F17 → no contradiction ✓
Fix for ID-02 (language removed) → checked against: UploadOptions, ParseEvent, F15, F22 → no contradiction ✓
```

If any regression found → treat it as a new violation and return to 2a.
If no regressions → Return to main session with `STATUS: FIXED`

### Step 3: Handle Subagent Result (main session)

Parse the subagent's returned status:

- **`STATUS: PASS`** — No violations found. Return to the `understand` flow.
- **`STATUS: FIXED`** — All violations fixed and verified. Return to the `understand` flow.

The `understand` skill will re-present the updated procedure file links to the user with the same selection options.

## Decision Summary

```
Main session: Dispatch subagent
Subagent: Run Codex → Write audit/result.md → PASS? → return STATUS: PASS
                                             → FAIL? → Fix all → Verify each → Regression scan → return STATUS: FIXED
                                                                                               → regression? → loop back to Fix
Main session: Receive status → Return to understand Step 3
```

**The subagent does NOT return to the main session with known unfixed violations.**
