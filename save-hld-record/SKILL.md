---
name: save-hld-record
description: Saves the understand + HLD output as artifact files for quality analysis. Records original output, audit issues, and final output to .auto-tdd/{name}/ directory.
---

# Save HLD Record

Saves the current understand + HLD artifacts to disk for later quality analysis. Uses the same directory structure and naming convention as auto-tdd.

## When to Use

- **Manual flow**: Invoked from `understand` Step 3c when the user selects the save option.
- **auto-tdd flow**: Invoked by auto-tdd at Phase 1 and Phase 2 boundaries to record artifacts automatically.

## Process

### Step 1: Determine Requirement Name

Derive a short, filesystem-safe name from the current task's summary (from `understand` Step 2 output). Use lowercase kebab-case, max 50 chars. Example: "home-v1-tab-switching", "fix-login-redirect".

### Step 2: Write Original Output

Write the combined Requirements Analysis + HLD Design (the full content produced by `understand` Step 4 format) to:

```
.auto-tdd/{requirement_name}/understand_hld.md
```

### Step 3: Check for Audit Data

Check whether `understand-hld-check` was run in the current conversation (option 3 in Step 3c).

- **Audit was NOT run** → Skip Steps 4–5. Go to Step 6.
- **Audit was run** → Proceed to Step 4.

### Step 4: Write Audit Issues

Write the Codex audit violations to:

```
.auto-tdd/{requirement_name}/understand_hld_audit.md
```

Content: the violation list returned by Codex — each violation ID, category, description, and suggested fix. Verbatim from the audit output.

### Step 5: Write Final Output

Write the post-fix combined Requirements Analysis + HLD Design to:

```
.auto-tdd/{requirement_name}/understand_hld_final.md
```

Content: the corrected version after all audit violations were fixed.

### Step 6: Confirm

Output exactly:

> **HLD record saved to `.auto-tdd/{requirement_name}/`.**

Then return to `understand` Step 3c — re-present the same four options (code / testcase / audit / save) so the user can continue the workflow.

## Rules

1. **Artifact files are immutable after creation** — never overwrite a file written by a prior step
2. **Write verbatim content** — do NOT summarize, compress, or reformat the artifacts
3. **Directory creation** — create `.auto-tdd/{requirement_name}/` if it does not exist
4. **No duplicate records** — if `.auto-tdd/{requirement_name}/understand_hld.md` already exists, append a numeric suffix to the directory name (e.g., `{requirement_name}-2`)
