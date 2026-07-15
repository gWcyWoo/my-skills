---
name: prs
description: Create a copy-ready GitHub pull-request link and an evidence-based PR summary. Use when the user invokes `$prs` or `prs`, asks for a PR summary or PR description, or wants a concise link plus New Features, Bug Fixes, and Testing Suggestions. Support `--details` and `—details` for an expanded technical summary.
---

# PR Summary

Produce two copy-ready outputs: the PR URL and an idiomatic technical-English summary. Read only; never edit, comment on, approve, merge, or otherwise mutate the PR unless the user separately requests that action.

## Resolve the PR

1. Use a supplied PR number or URL when present.
2. Otherwise, resolve the PR for the current repository and branch with GitHub CLI.
3. Read authoritative PR metadata, base/head refs, commits, changed files, diff, and checks. Inspect the relevant production and test changes before describing behavior.
4. If authentication fails, no PR exists, or multiple candidates remain, report the exact blocker and request the missing choice. Never infer a PR from a branch name alone.

Ground every claim in the current PR diff or completed check output. Do not claim that tests passed merely because test files exist.

## Select the Output Mode

Use concise mode by default. Use detailed mode when the request contains either `--details` or `—details`.

## Concise Mode

Keep the description short and suitable for direct use as a PR body. Avoid file-level implementation details, internal class names, review history, and exhaustive edge cases.

Output in this order:

1. `PR URL` — show the complete URL on its own line, using the URL itself as the Markdown link label so it is clickable and easy to copy.
2. `PR Summary` — provide one fenced `markdown` block with:
   - `## Summary`: one or two sentences.
   - `## New Features`: short user- or operator-visible bullets.
   - `## Bug Fixes`: short before/after bullets.
   - `## Testing Suggestions`: actionable QA scenarios describing the action and expected result.

Use at most five bullets per section. If the diff contains no evidence for a category, say so in one short sentence instead of inventing content. Write the summary in idiomatic technical English unless the user requests another language.

## Detailed Mode

Retain the same URL-first format, then expand the fenced PR description with only relevant sections:

- Summary
- New Features
- Bug Fixes
- User-Facing Rules and QA Scenarios
- Implementation Details
- Compatibility, Migration, and Risk Notes
- Verification Completed
- Additional Testing Suggestions

Describe important behavior boundaries, key affected modules, before/after behavior, compatibility concerns, and actual verification evidence. Distinguish completed verification from recommended testing.

## Writing Rules

- Lead with observable behavior, not development chronology.
- Prefer product language over repository jargon in concise mode.
- Make testing suggestions reproducible: setup, action, and expected result.
- Consolidate related changes; do not turn every changed file or test into a bullet.
- Mention migrations, configuration defaults, limits, concurrency, refunds, or failure handling only when supported by the diff and relevant to rollout or QA.
- Do not include a generic test command when a more useful user-flow test can be stated.
