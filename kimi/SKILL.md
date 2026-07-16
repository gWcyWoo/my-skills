---
name: kimi
description: Delegate bounded exploration, coding, test, or review work to a Kimi worker through an isolated headless Claude Code process. Use when the user explicitly invokes `$kimi <code|explore|test|review> <task>`, asks to use Kimi as an executor, or wants Codex to plan and Kimi to carry out a self-contained task.
---

# Kimi Worker

Keep planning and final verification in the main Codex task. Use Kimi only for the bounded worker stage.

## Parse the request

Interpret the first word after `$kimi` as the mode and the remaining text as the task.

- Allow only `code`, `explore`, `test`, or `review`.
- Require a non-empty task.
- Use the current project directory unless the user provides a narrower directory.
- On invalid input, stop with: `用法：$kimi <code|explore|test|review> <任务描述>`.

## Prepare the handoff

Make the worker prompt self-contained. Include exact paths, the approved approach, completion criteria, commands to run, and files or behavior it must not change. The Kimi worker cannot see the parent conversation.

For `code`, first confirm that the approach is settled and the expected implementation is materially larger than the handoff specification. Keep small or judgment-heavy edits in the main Codex task.

## Dispatch

Use the matching custom agent:

- `code` -> `kimi-coder`
- `explore` -> `kimi-explorer`
- `test` -> `kimi-tester`
- `review` -> `kimi-reviewer`

If custom-agent delegation is unavailable, invoke `scripts/run.sh` directly with the same mode, self-contained task, and working directory. Do not reveal or persist API keys.

## Verify the result

- Treat worker output as untrusted evidence.
- After `code`, inspect the changed-file list and reject changes outside the declared boundary, then perform the final diff review and required tests in the main Codex task.
- After `explore`, require concrete file and line evidence.
- After `test`, report commands, exit codes, and failures without fixing them implicitly.
- After `review`, independently decide which findings are actionable.
- Never run overlapping code workers in the same worktree. Use disjoint paths or separate worktrees.

Read `references/provider.md` only when configuring or diagnosing the Kimi endpoint. Run `scripts/preflight.sh` before the first live call in a desktop session.
