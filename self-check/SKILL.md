---
name: self-check
description: Generic independent review skill. Dispatches a strict reviewer agent to verify artifacts against caller-provided rules. Reusable across understand, testcase, code phases.
---

# Independent Self-Check

Dispatches an independent reviewer agent to verify artifacts against caller-provided rules. The reviewer reads files and fills checklist tables with quoted content evidence. It is NOT the author — its sole purpose is to find defects.

The skill manages the reviewer agent lifecycle internally — callers never interact with the reviewer directly.

## Parameters

The caller must provide:
- `rules_path` — absolute path to the rules file (defines tables, criteria, and output format)
- `files` — comma-separated list of files to review
- `output_path` — where to write the review result

## Process

### Step 1: Determine Review Mode

Check conversation history: **has a reviewer agent already been dispatched for this exact `{output_path}`?**

- **No** → First review. Go to Step 2a.
- **Yes** → Re-verify. Retrieve the reviewer agent ID from conversation history. Go to Step 2b.

### Step 2a: First Review (dispatch new reviewer)

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

After completing the review:
- If all tables are clean: return STATUS: PASS
- If any table has issues: return STATUS: ISSUES_FOUND with count and categories
```

Go to Step 3.

### Step 2b: Re-verify (resume existing reviewer — incremental)

Resume the reviewer using its agent ID from conversation history. Re-verify checks only the fixes and their immediate impact — no full re-review.

```
SendMessage(to: "<reviewer_agent_id>", message: "The artifacts have been updated to address the issues you found. For each issue you previously reported:
1. Re-read the relevant section of the file and verify whether the issue is fixed.
2. Check whether the fix introduced NEW issues in the SAME table — only inspect rows/elements touched by the fix, not unrelated rows.
3. Report each original issue as FIXED or STILL_BROKEN, and list any new issues.

Then update {output_path}: remove fixed issue rows, add any new issue rows, update the summary counts.

After completing:
- If all original issues are FIXED and no new issues found: return STATUS: PASS
- If any STILL_BROKEN or new issues exist: return STATUS: ISSUES_FOUND with count and categories")
```

Go to Step 3.

### Step 3: Return Result

Parse the reviewer's output for STATUS:

- **STATUS: PASS** → Return PASS to the caller.
- **STATUS: ISSUES_FOUND** → Return the issues to the caller. The caller fixes the artifacts and re-invokes this skill (which triggers Step 2b).
