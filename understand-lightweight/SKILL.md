---
name: understand-lightweight
description: Use as the lightweight understanding step when no formal HLD is needed, to explore code via `my-explore` or `my-explore-0`, identify the gap between requirement and current state, discuss with the user, and confirm the result.
---

# Lightweight Understanding

Produce a confirmed gap analysis without entering the formal `understand` plus `hld` workflow. Keep the user in the loop, and keep source-code navigation delegated to the `my-explore` family.

## What This Is For

- Lightweight understanding before implementation, when a full formal HLD is unnecessary
- Reusing `my-explore` or `my-explore-0` results instead of dumping source into the current session
- Clarifying the real gap between current behavior and target behavior before code or tests

## What This Is Not For

- Formal HLD with integration contracts
- Writing tests or code
- Direct source-code reading in this skill

## Step 1: Explore

Read the user's requirement first. Then choose the exploration variant by execution context:

- Main session -> use `my-explore`
- Already inside a subagent that cannot recursively dispatch -> use `my-explore-0`

Pass the requirement context so exploration has a clear search target. Do not read source files directly here; the exploration playbook is owned by `my-explore` and `my-explore-0`, which follow `my-explore/dispatch-prompt.md`.

## Step 2: Understand the Gap

Based on the exploration results and the user's requirement, think through:

**Bug fix:** What is the user reporting? What does the code actually do? Where is the root cause? How should it be fixed?

**New feature or change:** What does the user want? What does the code currently look like? What is the gap between the two? How should it be implemented?

## Step 3: Discuss

If anything is unclear, ask. Do not guess and do not assume.

This is a conversation, not a one-shot output. Go back and forth with the user until both sides are clear on:

- What the problem or requirement is
- How to solve or implement it

## Step 4: Confirm

When the understanding is clear, present the confirmed result in this shape:

**For a bug fix**

Symptom: `<one sentence, in user's words>`
Root cause: `<one sentence + file:line>`
Fix approach: `<one sentence>`
Files in scope: `<path:line, one per line>`
Confidence: `high | medium | low`

**For a new feature or change**

Goal: `<one sentence, in user's words>`
Current state: `<one sentence + file:line>`
Gap: `<one sentence>`
Approach: `<one to three sentences>`
Files in scope: `<path:line, one per line>`
Confidence: `high | medium | low`

**STOP and wait for user confirmation.** Do NOT proceed until confirmed.

## Final Reminders

- NEVER read source code directly. Always go through `my-explore` or `my-explore-0`.
- NEVER guess when the requirement is ambiguous. Ask the user.
- This skill is lightweight understanding only. If the change needs a formal HLD, use `understand`.
- Do not write tests or code in this skill. Those are downstream.
