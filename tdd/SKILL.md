---
name: tdd
description: Default development workflow. TDD for requirements and bug fixes. Runs in the main session with the user in the loop.
---

# TDD

For changes that need a formal HLD (High-Level Design), use the `understand` skill instead.

## Step 1: Understand

Invoke the `my-explore` skill to explore the codebase and understand the requirement or bug.

- If anything is unclear, **STOP and ask the user** — do not guess or assume

After exploring, **STOP and present the understanding to the user**:
- Summarize the requirement or bug, affected files, and what needs to change
- Wait for the user to confirm, correct, or add details
- Do NOT proceed until the user confirms

## Step 1.5: Trivial Change Check

After understanding is confirmed, evaluate whether the change is **trivial** (both: diff ≤ 5 lines AND low-risk category like typo/config/comment/rename).

- **Trivial** → skip to Step 3, but skip rule loading (3a) — implement directly. Inform the user.
- **Not trivial** (logic/algorithm/state/API/security changes, even if ≤ 5 lines) → proceed to Step 2.

## Step 2: Test Cases & Review

Read `write-tests.md` from this skill's directory and follow its instructions.

## Step 3: Implement & Review

Read `code.md` from this skill's directory. Load coding standards via subagent, implement, then review with user.

## Step 4: Lint, Test & Done

Read `verify.md` from this skill's directory and follow its instructions.
