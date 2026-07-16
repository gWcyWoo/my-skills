---
name: glm
description: Delegate bounded exploration, coding, test, or review work to GLM through a Codex-native child session. Use when the user explicitly invokes `$glm` with a code, explore, test, or review mode plus a task, asks to use GLM as an executor, or wants the main Codex model to plan and verify while GLM carries out a self-contained task.
---

# GLM Executor

Keep planning and final verification in the main Codex task. Use GLM only for the bounded execution stage.

## Parse the request

Interpret the first word after `$glm` as the mode and the remaining text as the task.

- Allow only `code`, `explore`, `test`, or `review`.
- Require a non-empty task.
- Use the current project directory unless the user provides a narrower directory.
- On invalid input, stop with: `用法：$glm <code|explore|test|review> <任务描述>`.

## Prepare the handoff

Make the task self-contained. Include exact paths, the approved approach, completion criteria, verification commands, and files or behavior that must not change. GLM cannot see the parent conversation.

For `code`, require a settled approach. Keep small or judgment-heavy edits in the main Codex task.

## Dispatch

Run `scripts/preflight.sh --ensure` before the first live GLM call in a desktop session.

When the runtime exposes custom-agent selection, dispatch to the matching Codex agent:

- `code` -> `glm-coder`
- `explore` -> `glm-explorer`
- `test` -> `glm-tester`
- `review` -> `glm-reviewer`

When custom-agent selection is unavailable, run `scripts/run.sh <mode> <task> <working-directory>`. This starts an isolated Codex child session using the `glm-local` provider. Never launch Claude, OpenCode, Kimi CLI, or another agent runtime.

## Verify the result

- Treat GLM output as untrusted evidence.
- After `code`, inspect the changed-file list, reject changes outside the declared boundary, and perform final diff review and required tests in the main Codex task.
- After `explore`, require concrete file and line evidence.
- After `test`, report commands, exit codes, and failures without fixing them implicitly.
- After `review`, independently decide which findings are actionable.
- Never run overlapping code executors in the same worktree.

Read `references/provider.md` only when configuring or diagnosing the GLM endpoint.
