# Claude Code Harness Reference

Authoritative reference for the harness-layer mechanisms that skills in this project rely on. Compiled from official Anthropic documentation and tracked issues. Read this before designing any skill that depends on subagent dispatch, tool restriction, permission control, or hook-based enforcement.

**Last verified:** 2026-04-08 against `code.claude.com/docs/en/sub-agents` and `code.claude.com/docs/en/permissions`.

---

## 1. Subagent — what it is at the harness level

- A markdown file with YAML frontmatter, **loaded by the harness at session start**.
- Owns an **independent context window**, system prompt, tool inventory, and permissions.
- Invoked from the parent session via the `Agent` tool (formerly `Task`, renamed in 2.1.63 — `Task(...)` still works as an alias).
- **Critical limitation: subagents cannot spawn subagents.** `Agent(...)` syntax inside a subagent definition has no effect.

---

## 2. Subagent locations and priority

| Location | Scope | Priority |
|---|---|---|
| Managed settings (organization policy) | Org-wide | 1 (highest) |
| `--agents` CLI flag (JSON) | Current session | 2 |
| `.claude/agents/` | Current project | 3 |
| `~/.claude/agents/` | All projects of current user | 4 |
| Plugin's bundled `agents/` | Wherever the plugin is enabled | 5 (lowest) |

**Same name → higher priority wins.** Plugin subagents do **not** support `hooks` / `mcpServers` / `permissionMode` (security restriction).

---

## 3. Frontmatter fields (full list)

Only `name` and `description` are required.

| Field | Purpose |
|---|---|
| `name` | Unique identifier — **lowercase + hyphens only** |
| `description` | Trigger judgment text — what makes Claude delegate to this agent |
| `tools` | **Allowlist** — omit to inherit all parent tools |
| `disallowedTools` | **Denylist** — removed from inherited or specified pool |
| `model` | `sonnet` / `opus` / `haiku` / full ID (e.g. `claude-opus-4-6`) / `inherit`. Default: `inherit` |
| `permissionMode` | `default` / `acceptEdits` / `auto` / `dontAsk` / `bypassPermissions` / `plan` |
| `maxTurns` | Max agentic turns before auto-stop |
| `skills` | Skills to **inject in full** at startup (not just made callable) |
| `mcpServers` | MCP servers scoped to this subagent — inline definition or named reference |
| `hooks` | Lifecycle hooks scoped to this subagent |
| `memory` | `user` / `project` / `local` — enables cross-session memory |
| `background` | `true` makes it always run as a background task |
| `effort` | `low` / `medium` / `high` / `max` (max is Opus 4.6 only) |
| `isolation` | `worktree` runs the subagent in a temporary git worktree |
| `color` | UI display color in task list and transcript |
| `initialPrompt` | Auto-submitted as first user message when this agent runs as the main session agent |

---

## 4. Tool allowlist / denylist — exact semantics

```yaml
tools: Read, Grep, Glob, Bash               # allowlist (only these usable)
disallowedTools: Write, Edit                # denylist (removed from inherited pool)
```

- **If both are set**: `disallowedTools` is applied first, then `tools` is resolved against the remaining pool. A tool listed in both is removed.
- **Omit `tools`**: inherits all parent tools (including MCP).
- **MCP tool naming**: `mcp__<server>__<tool>` (e.g. `mcp__probe__extract_code`).

### Subagent-spawn control (only meaningful for an agent running as the main thread)

```yaml
tools: Agent(worker, researcher), Read, Bash   # can only spawn these two
tools: Agent, Read, Bash                       # can spawn any subagent
# Agent omitted entirely → cannot spawn anything
```

`Agent(...)` syntax has no effect inside ordinary subagent definitions because subagents themselves cannot spawn.

---

## 5. Permission hierarchy and known pitfalls

Permission resolution order (any layer that denies → no lower layer can allow):

1. Managed settings (org policy)
2. CLI flags (`--allowedTools` / `--disallowedTools`)
3. Local project settings
4. Shared project settings
5. User settings

### Known issues (open / acknowledged on GitHub)

- **#30161** — `deny` rules in settings apply to **both** main session and all subagents simultaneously. **No way to deny a tool to the main conversation while allowing subagents to use it.**
- **#25000** (BUG) — Sub-agents sometimes bypass `deny` rules and per-command approval (security risk).
- **#6005** — `disallowed-tools` in subagent frontmatter is still evolving.
- **#29610** — `bypassPermissions` does NOT bypass `Read`/`Bash` for paths outside the project root in background subagents.

### Agent-level deny syntax

```jsonc
"permissions": {
  "deny":  ["Agent(Explore)"],                    // forbid a subagent type
  "allow": ["Agent(Plan)", "Agent(my-reviewer)"]  // allowlist subagent types
}
```

---

## 6. Permission modes

| Mode | Behavior |
|---|---|
| `default` | Standard permission prompts |
| `acceptEdits` | Auto-accept file edits (except in protected directories) |
| `auto` | Background classifier reviews commands and protected-directory writes |
| `dontAsk` | Auto-deny all permission prompts (explicitly allowed tools still work) |
| `bypassPermissions` | Skip all permission prompts |
| `plan` | Plan mode |

Subagents inherit the parent's permission context and may override it, except where the parent mode takes precedence.

---

## 7. MCP server scoping per subagent

```yaml
mcpServers:
  - playwright:                          # inline definition — visible only to this subagent
      type: stdio
      command: npx
      args: ["-y", "@playwright/mcp@latest"]
  - github                               # reference an already-configured server
```

**Key technique for context savings:** define an MCP server inline in a subagent's frontmatter (instead of in `.mcp.json`). Its tool descriptions then never enter the main session's context — they connect only when the subagent starts and disconnect when it finishes. This is a primary lever for shrinking main-session token cost.

---

## 8. Built-in vs custom subagents

### Built-in (provided by the harness or plugins)

- `general-purpose` — full tool access.
- `Explore` — **all tools except `Agent`, `ExitPlanMode`, `Edit`, `Write`, `NotebookEdit`**. ⚠️ This means `Bash` and `Read` are still in the inventory — empirically the cause of `find`/`ls`/`cat` regressions in our `my-explore` skill before we built the custom variant.
- `Plan`, `statusline-setup`, plus various plugin-provided agents (`code-reviewer`, `claude-code-guide`, etc.).

### Custom

- Must be named **lowercase + hyphens** → therefore **cannot override `Explore`** (capitalized) or any other capitalized built-in.
- Loaded from the locations in §2.

---

## 9. Hook system (used as the last resort for hard enforcement)

- Hooks can be declared in subagent frontmatter (subagent-scoped) or in project settings (event-scoped).
- **Hooks are executed by the harness, not the model** — so they are **truly hard** constraints, unlike prompt rules.
- `PreToolUse` hooks can intercept and reject specific tool calls based on arbitrary logic (file path, regex, env var, etc.).
- This is the **only available mechanism for restricting tools in the main session**, since the main session's tool inventory cannot be narrowed via subagent frontmatter.

---

## 10. Operational notes

- **Restart or `/agents`**: after creating a new agent file, you MUST restart the session **or** run `/agents` for the harness to pick it up. Files added mid-session are not auto-loaded.
- **`subagent_type` parameter** of the `Agent` tool accepts any loaded agent name — built-in or custom — and resolves through the priority hierarchy in §2.
- **`SendMessage(to: "<name>")`** continues a previously spawned named subagent with its full prior context preserved. Much cheaper than spawning a fresh subagent for follow-ups.
- **Subagents are loaded at session start** — you cannot "patch" a running subagent's tool inventory; you must restart.

---

## 11. How this project applies the above

| Requirement | Mechanism | Status |
|---|---|---|
| Prevent the exploration subagent from using Bash / Read on source | Custom `~/.claude/agents/my-explore.md` with strict `tools:` allowlist | ✅ in place — requires session restart or `/agents` to take effect |
| Keep test code, rules, and source out of the main session for `write-tests` | Dispatch a named `test-writer` subagent (`general-purpose` type) | ✅ in place |
| Restrict tools in the main session itself | **Only achievable via `PreToolUse` hooks** | ⏳ not yet implemented |
| Deny a tool to the main session but allow it in a subagent | **Not currently possible** at the harness level | ❌ blocked by GitHub #30161 |
| Save context by hiding an MCP server's tools from the main session | Inline `mcpServers:` in a subagent frontmatter | 💡 not yet exploited — opportunity |

---

## 12. Sources

- [Create custom subagents — Claude Code Docs](https://code.claude.com/docs/en/sub-agents)
- [Configure permissions — Claude Code Docs](https://code.claude.com/docs/en/permissions)
- [Issue #6005 — disallowed-tools in subagent frontmatter](https://github.com/anthropics/claude-code/issues/6005)
- [Issue #30161 — denyMainOnly permission scope](https://github.com/anthropics/claude-code/issues/30161)
- [Issue #25000 — sub-agents bypass deny rules (BUG)](https://github.com/anthropics/claude-code/issues/25000)
- [Issue #29610 — bypassPermissions and out-of-root paths (BUG)](https://github.com/anthropics/claude-code/issues/29610)

---

**Maintenance note:** This document is point-in-time. The harness evolves quickly — verify any field, behavior, or limitation against the live docs before relying on it for new skill design. When you discover new harness behavior worth recording, append a dated section rather than rewriting prior sections, so the history of what was true when remains visible.

---

## Raw materials

The original material this document was distilled from is preserved alongside it in `.harness-sources/`:

- `.harness-sources/sub-agents-doc.2026-04-08.md` — full WebFetch result of `code.claude.com/docs/en/sub-agents` (51 KB, 930 lines). This is the authoritative source for §1–10 above. Cross-check any specific claim here against that file before quoting it externally.
- `.harness-sources/websearch-results.2026-04-08.md` — verbatim search results (queries, link lists, summaries) for the two WebSearch calls that surfaced the GitHub issues and the permissions doc. Use this to re-discover sources, not as primary evidence.

If you need to refresh the picture:
1. Re-fetch `code.claude.com/docs/en/sub-agents` and `code.claude.com/docs/en/permissions` and diff against the saved files.
2. Re-check the GitHub issues listed in §5 — they evolve, especially #30161 and #6005.
3. Append a new dated section to this document with what changed; do not silently overwrite the prior content.
