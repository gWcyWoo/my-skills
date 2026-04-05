---
name: tdd
description: Default development workflow. TDD for requirements and bug fixes. Runs in the main session with the user in the loop.
---

# TDD

For changes that need a formal HLD (High-Level Design), use the `understand` skill instead.

## Hard Rules

- **Steps are sequential.** Each step MUST be completed before starting the next. User saying "proceed" means proceed to the **next step**, not jump to implementation.
- **Every step that says "Invoke skill" MUST actually invoke it.** Do not inline, summarize, or skip skill invocations.

## Step 1: Understand

Invoke the `my-explore` skill to explore the codebase and understand the requirement or bug.

- If anything is unclear, **STOP and ask the user** — do not guess or assume

After exploring, **STOP and present the understanding to the user**:
- Summarize the requirement or bug, affected files, and what needs to change
- Wait for the user to confirm, correct, or add details
- Do NOT proceed until the user confirms

## Step 2: Test Decision

After understanding is confirmed, **STOP and ask the user**:

> Do you want to write test cases first?

- If **yes** → invoke the `write-tests` skill and follow its instructions. Then proceed to Step 3.
- If **no** → proceed directly to Step 3.

## Step 3: Implement & Review

Invoke the `code` skill and follow its instructions.

## Step 4: Lint, Test & Done

Read `verify.md` from this skill's directory and follow its instructions.
