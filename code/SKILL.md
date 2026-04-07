---
name: code
description: Load coding standards via comply, implement, then review with user. Reusable implementation step for any workflow.
---

# Implement & Review

## 1. Load coding standards

Read and follow `comply/SKILL.md` to load relevant coding standards via subagent.

## 2. Implement

Apply the returned rules during implementation. Keep changes minimal and focused.

## 3. Review

After implementation is complete, **STOP and ask the user**:

> Implementation complete. Would you like to review before running lint and tests?

- If yes → wait for feedback, apply changes.
- If no → proceed.
