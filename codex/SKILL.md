---
name: codex
description: Executor for complex reasoning and L7 auditing. Accepts a pre-constructed prompt string and passes it verbatim to Codex CLI.
---

# Codex Executor

Passes a pre-constructed prompt string verbatim to Codex CLI. Caller constructs the prompt; this skill only executes and returns output.

## Execution

Run with `timeout: 600000` on the Bash tool call:

```bash
codex exec \
  -m gpt-5.4 \
  -c model_reasoning_effort=\"high\" \
  --sandbox read-only \
  --skip-git-repo-check \
  --ephemeral \
  2>/dev/null \
  "$(cat <<'PROMPT'
<prompt string from caller>
PROMPT
)"
```

## Output

Return stdout **verbatim**. Do NOT interpret or modify.

- Exit 0 → return stdout
- Exit 124 → return `"CODEX_TIMEOUT"`
- Other → return `"CODEX_ERROR: exit code {N}"` + stdout
