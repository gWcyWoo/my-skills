---
name: self-check
description: Author-side self-review against review rules. Runs inside the current agent — no separate agent dispatch. Catches defects before the independent review.
---

# Self-Check

Author-side quality gate. The current agent reads the review rules file and checks its own output against every table and criterion. Defects found are fixed immediately — no separate agent, no round-trip.

This is NOT the independent review. The independent `review` skill dispatches a separate adversarial reviewer agent. Self-check runs first to reduce the number of issues the reviewer finds, making the review a single-pass verification rather than a multi-round fix cycle.

## Parameters

The caller must provide:
- `rules_path` — absolute path to the rules file (same file used by the `review` skill)
- `files` — comma-separated list of files to check (the agent's own output)
- `output_path` — where to write the self-check record

## Process

### Step 1: Read Rules

Read the rules file at `{rules_path}`. Extract every table definition, its row criteria, and pass/fail conditions.

### Step 2: Check Each Table

For each table defined in the rules, fill it with the same rigor as the independent reviewer:

1. **Count source elements** — how many rows should this table have? Count from the source files.
2. **Fill the table** — for each row, check the criterion against the actual file content. Quote the evidence.
3. **Mark status** — each row gets ✅ (pass) or ❌ (fail with issue description).
4. **Verify row count** — confirm the table row count matches the source element count. If mismatch, add the missing rows.

### Step 3: Fix Issues

For each ❌ row:

1. **Diagnose** — what specifically is wrong?
2. **Fix** — modify the output file to resolve the issue.
3. **Re-check the fixed row** — re-read the file and verify the fix resolves the issue. Update the row to ✅ if fixed.

### Step 4: Write Record

Write all tables to `{output_path}` with this format:

```markdown
## Self-Check Record

### [Table Name]
| ... (same columns as the rules file defines) ... | Status |
|---|---|
| ... | ✅ |
| ... | ✅ (fixed: [what was wrong and how it was fixed]) |
| ... | ❌ UNFIXABLE: [reason] |

### Summary
- Tables checked: N
- Total rows: N
- Issues found: N
- Issues fixed: N
- Unfixable: N
```

Rows that were fixed must show both the original issue and the fix applied — this enables retrospective analysis of what the author caught vs. what the reviewer caught.

### Step 5: Return

- If all issues were fixed (0 unfixable) → return to the caller's next step.
- If any issue is unfixable (e.g., requires HLD change, missing input data) → report the unfixable issues to the caller so it can escalate.
