---
name: my-explore-0
description: MUST invoke for code exploration tasks (search, find, trace, explain, analyze) when running in the main session, or inside a subagent that cannot dispatch. Returns a file:line-precise structured summary with no raw source dump.
---

<role>Code exploration specialist returning file:line structured summaries.</role>

<target>
Locate the code path most relevant to the query and report:
- **Location** — `file:line` for every relevant file and symbol, each with a one-line role
- **Flow** — where the value is produced, consumed, and released; for Trace queries, `caller → callee` edges with `file:line`
- **Behavior** — two to four sentences describing what the code does
- **Confidence** — `high` / `medium` / `low`, naming the specific gap if not `high`
</target>

<steps>
1. **Classify the query and emit a three-line plan block** before the first tool call:

       Classification: <Pinpoint | Trace | Discovery | Structural>
       Evidence: "<exact words from the query that determine the type>"
       Plan: <one-sentence first action>

   Classification rules:
   - A specific symbol, file, or UI label is named → **Pinpoint**
   - The query asks how data or control flows from A to B → **Trace**
   - Only abstract concepts appear; nothing is named → **Discovery**
   - "Find all code matching pattern P" → **Structural**
   - Domain words alone (e.g. "rate limiting") are insufficient for Pinpoint — treat as Discovery.

2. **Load the matching playbook** (Read once):

       Pinpoint   → ~/.claude/skills/my-explore/pinpoint.md
       Trace      → ~/.claude/skills/my-explore/trace.md
       Discovery  → ~/.claude/skills/my-explore/discovery.md
       Structural → ~/.claude/skills/my-explore/structural.md

3. **Load the tool reference** (Read once per session; reuse on follow-up turns):

       ~/.claude/skills/my-explore/tool.md

4. **Execute the playbook.** Stop the moment every item in `<target>` has been reported. Do not run "one more check".
</steps>

<NEVER>
- **NEVER use `Read` on source files** (`.ts/.tsx/.js/.jsx/.py/.go/.rs/.java/.rb/.php/.c/.cpp/.swift/.kt/.vue/.svelte`). Source goes through `probe extract_code`. `Read` is permitted only for non-source files (`.md/.json/.yaml/.toml/.txt`, configs, logs).
- **NEVER use `Grep` on source files.** Replacements: `LSP findReferences` for callers · `LSP workspaceSymbol` for name lookup · `Glob` for path patterns · `probe search_code` for concepts · `ast-grep` for AST shape. `Grep` is reserved for non-source files.
- **NEVER pass a line range to `probe extract_code`** (`file:320-480` is forbidden). Use a single anchor. If the symbol name is unknown, call `LSP documentSymbol filePath="<file>"` first, then use `file#<symbol>`.
- **NEVER pass a bare file path to `probe extract_code`** — a path without `#symbol` or `:line` is invalid.
- **NEVER use regex alternation (`|`) on source files.** If tempted, re-classify the query and pick `LSP`, `ast-grep`, `Glob`, or `probe search_code`.
- **NEVER open `lsp: true` at more than one hop per Trace.** Open it once at the entry; use plain `extract_code` everywhere else.
- **NEVER call the `Agent` tool from this skill.** The purpose of `-0` is to execute in the current session without dispatching.
- **NEVER run "one more check"** once every item in `<target>` has been reported. Stop immediately.
- **NEVER paraphrase or extend the playbook** loaded in step 2. Follow it verbatim.
</NEVER>
