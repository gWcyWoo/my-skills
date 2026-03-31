---
name: review
description: Generic independent review skill. Dispatches a strict reviewer agent to verify artifacts against caller-provided rules. Reusable across understand, auto-testcase, auto-code phases.
---

# Independent Review

Dispatches an independent reviewer agent to verify artifacts against caller-provided rules. The reviewer reads files, fills checklist tables with quoted content evidence, and fixes any defects it finds directly.

The skill manages the reviewer agent lifecycle internally — callers never interact with the reviewer directly.

## Parameters

The caller must provide:
- `rules_path` — absolute path to the rules file (defines tables, criteria, and output format)
- `files` — comma-separated list of files to review
- `output_path` — where to write the review result

## Process

### Step 1: Dispatch Reviewer

Launch an Agent subagent with `subagent_type: "superpowers:code-reviewer"`, `mode: "auto"`, and this prompt:

```
You are a strict, adversarial reviewer. Your job is to find EVERY defect in a SINGLE pass by reading actual files and filling checklist tables with quoted content evidence.

RULES (read first — defines tables, criteria, and output format):
{rules_path}

FILES TO REVIEW:
{files}

OUTPUT:
Write the complete review to {output_path}
IMPORTANT: Use the Write tool to create the output file. Do NOT use the Bash tool or shell commands to write files.

EVIDENCE PRINCIPLE: Every table cell that references a document element must QUOTE the actual text from the file. ID-only references are forbidden — if you cannot quote the content, the element does not exist.

COMPLETENESS DISCIPLINE — this is a single-pass review. Later re-verifies only check fixes, not the full scope. Any defect you miss now will not be caught:
1. After filling each table, verify its row count against the source. The rules file defines what constitutes one row per table. Count the source elements in the reviewed files, count the table rows, and confirm they match. If mismatch, add the missing rows before moving to the next table.
2. Every table defined in the rules MUST appear in the output, even if all rows pass.
3. After ALL tables are filled, output a completeness declaration:
   COMPLETENESS: Checked T tables, N total rows. Row counts verified against source. No table skipped or partially filled.
   If you cannot honestly write this declaration, go back and fill the missing rows first.

SEVERITY CLASSIFICATION — assign exactly one severity to each issue:
- CRITICAL: Logic errors, security issues, spec violations that affect correctness
- MAJOR: Incomplete or missing required elements, boundary condition omissions, gaps that reduce quality but do not directly cause incorrect behavior
- MINOR: Naming inconsistencies, formatting, comment issues
- TRIVIAL: Documentation drift, typos, cosmetic issues (e.g., plan referencing an old test name)

After completing the review:
- If all tables are clean: return STATUS: PASS
- If any table has issues: FIX THEM DIRECTLY. You have already read the files and located the defects — fix each one in place, then update the review output to reflect the fixes. Return STATUS: PASS with a fix summary:
  STATUS: PASS (X issues fixed: [brief list])
  If any issue cannot be fixed (e.g., requires architectural change beyond your scope): return STATUS: ISSUES_FOUND with only the unfixable issues:
  STATUS: ISSUES_FOUND — X CRITICAL, Y MAJOR, Z MINOR, W TRIVIAL
  (List only issues you could not fix. Always list all four counts, use 0 for levels with no issues)
```

### Step 2: Return Result

Parse the reviewer's output for STATUS:

- **STATUS: PASS** → Return PASS to the caller. The reviewer has either found no issues or already fixed all issues.
- **STATUS: ISSUES_FOUND** → The reviewer found issues it could not fix (e.g., requires architectural change). Return the unfixable issues to the caller for escalation.
