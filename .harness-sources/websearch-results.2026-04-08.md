# Raw WebSearch results — harness research, 2026-04-08

These are the verbatim results returned by the two WebSearch calls during this session. Preserved here so the distillation in `../HARNESS_REFERENCE.md` can be re-verified later.

---

## Search 1

**Query:** `Claude Code restrict subagent tools allowed disallowed list permissions 2026`

**Links returned:**

- [Configure permissions - Claude Code Docs](https://code.claude.com/docs/en/permissions)
- [Configure permissions - Claude API Docs](https://platform.claude.com/docs/en/agent-sdk/permissions)
- [Claude Code Permissions | Developing with AI Tools | Steve Kinney](https://stevekinney.com/courses/ai-development/claude-code-permissions)
- [Lock Down Claude Code With 5 Permission Patterns - DEV Community](https://dev.to/klement_gunndu/lock-down-claude-code-with-5-permission-patterns-4gcn)
- [Claude Agent SDK | Promptfoo](https://www.promptfoo.dev/docs/providers/claude-agent-sdk/)
- [Support denyMainOnly permission scope: restrict tools to subagents only · Issue #30161 · anthropics/claude-code](https://github.com/anthropics/claude-code/issues/30161)
- [[BUG] Sub-agents bypass permission deny rules and per-command approval — security risk · Issue #25000 anthropics/claude-code](https://github.com/anthropics/claude-code/issues/25000)
- [Claude Code --dangerously-skip-permissions: 5 Modes, Only 1 Nuclear](https://www.morphllm.com/claude-code-dangerously-skip-permissions)
- [Claude Code auto mode: a safer way to skip permissions](https://www.anthropic.com/engineering/claude-code-auto-mode)
- [Feature Request: Add `disallowed-tools` to sub-agent frontmatter for more flexible permissions · Issue #6005 · anthropics/claude-code](https://github.com/anthropics/claude-code/issues/6005)

**Summary returned by the search tool:**

> Based on the search results, here's what I found about restricting subagent tools in Claude Code:
>
> ## Allowed and Disallowed Lists for Subagents
>
> You can add rules to the deny array in your settings or use the --disallowedTools CLI flag to disable specific agents.
>
> ### Permission Configuration Methods
>
> MCP permission rules follow a format like `mcp__<server>__<tool>`, and you can deny specific agents like the Explore agent to prevent Claude from spawning a read-only exploration subprocess.
>
> For subagent-specific permissions, you can use the format `"deny": ["Agent(Explore)"], "allow": ["Agent(Plan)", "Agent(my-reviewer)"]` to control which subagents are available.
>
> ### Permission Hierarchy
>
> The permission hierarchy includes managed settings, command line arguments (--allowedTools, --disallowedTools), local project settings, shared project settings, and user settings. If a tool is denied at any level, no lower level can allow it.
>
> ### Current Limitations
>
> There are ongoing feature requests to improve subagent permission controls. When a tool is denied via settings or hook decisions, the restriction applies equally to the main conversation and all subagents, with no way to deny a tool to the main conversation while allowing subagents to use it.

---

## Search 2

**Query:** `Claude Code subagent frontmatter tools field whitelist Read Bash`

**Links returned:**

- [Create custom subagents - Claude Code Docs](https://code.claude.com/docs/en/sub-agents)
- [Best practices for Claude Code subagents](https://www.pubnub.com/blog/best-practices-for-claude-code-sub-agents/)
- [[BUG] Claude Code subagent YAML Frontmatter authoritive documentation · Issue #8501 · anthropics/claude-code](https://github.com/anthropics/claude-code/issues/8501)
- [Claude Code Custom Subagents: Complete Guide to @ Mention and Specialized Agent Teams | Claude Lab](https://claudelab.net/en/articles/claude-code/claude-code-custom-subagents-at-mention-guide)
- [bypassPermissions does not bypass Read/Bash for paths outside project root in background subagents · Issue #29610 · anthropics/claude-code](https://github.com/anthropics/claude-code/issues/29610)
- [claude-code-best-practice/best-practice/claude-subagents.md at main · shanraisshan/claude-code-best-practice](https://github.com/shanraisshan/claude-code-best-practice/blob/main/best-practice/claude-subagents.md)
- [Agent Skills in the SDK - Claude API Docs](https://platform.claude.com/docs/en/agent-sdk/skills)
- [Feature Request: Add `disallowed-tools` to sub-agent frontmatter for more flexible permissions · Issue #6005 · anthropics/claude-code](https://github.com/anthropics/claude-code/issues/6005)
- [How to create and use Subagents in Claude Code](https://www.cometapi.com/how-to-create-and-use-subagents-in-claude-code/)
- [Claude Code's Custom Agent Framework Changes Everything - DEV Community](https://dev.to/therealmrmumba/claude-codes-custom-agent-framework-changes-everything-4o4m)

**Summary returned by the search tool:**

> The search results provide comprehensive information about Claude Code subagent frontmatter, the tools field for tool whitelisting, and Read and Bash tools. Here's what I found:
>
> ## Claude Code Subagent Frontmatter Tools Field
>
> To restrict tools, use either the tools field (allowlist) or the disallowedTools field (denylist).
>
> ### Tools Field (Whitelist) Example
>
> The tools field can exclusively allow Read, Grep, Glob, and Bash, where the subagent can't edit files, write files, or use any MCP tools. Here's an example from the official documentation:
>
> ```yaml
> ---
> name: safe-researcher
> description: Research agent with restricted capabilities
> tools: Read, Grep, Glob, Bash
> ---
> ```
>
> ### How the Tools Field Works
>
> Omitting tools will let the subagent inherit all the main thread's tools; explicitly listing tools enforces a least-privilege model. To restrict tools, use either the tools field (allowlist) or the disallowedTools field (denylist).
>
> ### Read and Bash Tools
>
> The Read and Bash tools are commonly used in subagent configurations:
> - **Read**: Allows the subagent to read files
> - **Bash**: Enables shell command execution
>
> The tools field is a comma-separated allowlist of tools (e.g., Read, Write, Edit, Bash), and inherits all tools if omitted.

---

## Notes

- The WebSearch tool returns a model-distilled summary, not full page content. For the full official subagent doc, see `sub-agents-doc.2026-04-08.md` in this directory (fetched via WebFetch from `code.claude.com/docs/en/sub-agents`).
- The two summaries above quote text that appears verbatim in the official sub-agents doc — they are reliable for the specific claims they make, but should not be treated as a complete picture. Always cross-check against the full doc when designing new harness mechanisms.
- GitHub issue references (#30161, #25000, #29610, #6005, #8501) were surfaced by the search but not individually fetched. Re-fetch the issues directly if you need their current state — they evolve.
