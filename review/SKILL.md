---
name: review
description: External review helper for artifact-producing workflows such as `understand`, `auto-testcase`, and `auto-code`. Dispatches one reviewer through `my-subagent`, fixes any repairable defects directly, and returns control only with final review status.
---

# External Review

The review skill runs after the producing workflow has completed its own preparation phase. It dispatches `superpowers:code-reviewer` through `my-subagent`, fills the review tables, fixes any repairable defects directly, and never re-invokes the reviewer. Only defects that cannot be repaired safely are returned to the caller.

## Severity Definitions
- **CRITICAL**: Logic bugs, safety issues, or spec violations that break correctness.
- **MAJOR**: Missing or incomplete required elements or boundary/mode coverage lapses.
- **MINOR**: Naming mismatches, formatting errors, or documentation inaccuracies that do not break behavior.
- **TRIVIAL**: Cosmetic drift, typos, or visual polish issues.

## Parameters

The caller must provide:
- `rules_path` — absolute path to the rules file that defines the tables and expectations
- `files` — comma-separated artifact list the reviewer should inspect
- `output_path` — where to write the review result

## Process

### Step 1: Collect context
- Confirm the parent directory of `{output_path}` exists.
- The reviewer is expected to read the rules and every artifact listed in `files`. Do not inject extra context beyond those paths.

### Step 2: Dispatch the reviewer once
Open `~/.agents/skills/my-subagent/SKILL.md` and follow its observability rules.

Invoke `my-subagent` with `model: gpt-5.4`, `reasoning_effort: medium`, and the task prompt below. The reviewer must use `superpowers:code-reviewer` and nothing else. All issue classification and repair happens inside this prompt.

```
You are executing a review-dispatch task inside `my-subagent`.

Use `superpowers:code-reviewer` with isolated review context. The reviewer must receive only the review package below and no hidden context.

If you find defects, FIX THEM DIRECTLY before returning. Update the review tables so they describe the final post-fix state, and note how many issues were fixed.

Review package:

Rules path:
{rules_path}

Artifact paths:
{files}

Required output path:
{output_path}

Severity definitions:
- CRITICAL: logic errors, safety bugs, spec-violating behavior
- MAJOR: missing required elements or boundary coverage
- MINOR: naming/format/document issues
- TRIVIAL: cosmetic drift or typos

Requirements:
1. Read the rules from `{rules_path}` yourself.
2. Read every artifact in `{files}` yourself.
3. Follow the rules exactly.
4. Quote artifact text as evidence whenever the tables require it.
5. Assign each issue a severity bucket.
6. Write the complete review to `{output_path}`.
7. Modify the reviewed artifacts when needed to fix defects directly.
8. Re-read the changed artifacts after each fix and keep the review output in sync with the final state.
9. Review only the supplied artifacts and rules.

Final response:
- If all tables are clean with no changes needed: return `STATUS: PASS — 0 issues fixed`.
- If issues are found and all are fixed directly: return `STATUS: PASS — {fixed} issues fixed`.
- If any issue cannot be fixed safely: return `STATUS: ISSUES_FOUND — {unfixed} issues could not be fixed`.
```

Once the reviewer returns, capture the final `STATUS` line. Do not re-run the reviewer. Either it fixed the issues directly and returned `PASS`, or it surfaced an unrepaired blocker.

### Step 3: Explain the outcome
- **STATUS: PASS — 0 issues fixed** — pass the artifacts along to the next stage.
- **STATUS: PASS — X issues fixed** — pass the artifacts along to the next stage and preserve the review artifact as the repair record.
- **STATUS: ISSUES_FOUND — X issues could not be fixed** — surface the unrepaired blocker set to the caller and stop.
