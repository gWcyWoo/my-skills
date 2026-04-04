---
name: tdd
description: Use when implementing a requirement or bug fix in a JavaScript or TypeScript repository and you want a user-in-the-loop TDD workflow in the main session.
---

# TDD

This workflow is for JavaScript or TypeScript repositories that use `package.json`-based lint and test commands. For changes that need a formal HLD (High-Level Design), use the `understand` skill instead.

## Step 1: Understand

Invoke the `my-explore` skill to explore the codebase and understand the requirement or bug.

- If anything is unclear, **STOP and ask the user** - do not guess or assume

After exploring, **STOP and present the understanding to the user**:
- Summarize the requirement or bug, affected files, and what needs to change
- Wait for the user to confirm, correct, or add details
- Do NOT proceed until the user confirms

## Step 1.5: Trivial Change Check

After the user confirms the understanding, decide whether the change is **trivial**. A change is trivial only when both conditions are true:

- The implementation diff is 5 lines or fewer.
- The change is low risk, such as a typo, config edit, comment edit, or local rename with no behavior change.

- **Trivial**: skip Step 2 and Step 3a. Go directly to Step 3b and tell the user.
- **Not trivial**: proceed to Step 2.

Treat logic, algorithm, state, API, and security changes as non-trivial even if they fit within 5 lines.

## Step 2: Test Cases & Review

Read `write-tests.md` from this skill's directory and follow its instructions.

## Step 3: Implement & Review

Read `code.md` from this skill's directory. Use the `my-subagent` skill to load coding standards, implement, then review with the user.

## Step 4: Lint, Test & Done

Read `verify.md` from this skill's directory and follow its instructions.
