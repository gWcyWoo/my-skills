---
name: self-check
description: Use when the agent must perform an internal audit of artifacts, record findings, and fix any issues before handing work to the orchestrator.
---

# Author Self-Check

The self-check workflow runs entirely inside the agent. It reads the same rules that would go to the external reviewer but produces the findings itself, records them in `{output_path}`, and fixes any issues before yielding control back to the orchestrator. No subagents, reviewers, or external dispatching are invoked.

## Parameters

The caller must provide:
- `rules_path` — absolute path to the rules file that defines the tables and evaluation criteria
- `files` — comma-separated list of artifact paths to be validated
- `output_path` — where to write the self-check report

## Process

### Step 1: Gather context
- Ensure the parent directory of `{output_path}` exists.
- Load the rules and every artifact listed in `{files}`. Treat the rules as the source of truth for which tables must be completed and what constitutes a violation.

### Step 2: Run the internal audit
- For each table the rules require, record the same rows/columns that the reviewer would inspect. Quote evidence from the artifacts when marking rows as `✅` or `❌`.
- If a table reports failures, immediately document the issue and fix the underlying artifact before continuing. Keep running the self-check until all tables pass or you hit a blocker that needs user guidance.
- Maintain a brief status summary at the end of the report: `STATUS: PASS` when everything is clean, or `STATUS: ISSUES_FOUND — <count> issues` when anything still fails.

### Step 3: Write the report
- Save the completed tables, the reviewed artifact list, and the final status to `{output_path}`.
- If the final status is `STATUS: PASS`, the calling workflow may continue. If it is `STATUS: ISSUES_FOUND`, do not hand the artifacts to the orchestrator until you have fixed the remaining issues and updated the report to `PASS`.

The self-check artifact becomes a permanent record that the orchestrator and external reviewer can reuse as a trust anchor.
