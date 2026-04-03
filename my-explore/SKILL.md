---
name: my-explore
description: Use when a task requires narrow, source-of-truth code lookup or flow tracing before answering or editing.
---

# Code Navigation: rg + ast-grep + LSP

Once `my-explore` is invoked, it controls code exploration for the current task. Other skills may decide why code is being investigated, but they do not change how exploration works.

## Load Gate

**When this skill is invoked, you MUST re-read this file in full before any exploration step.** Do not rely on a cached or remembered version. Skills evolve — act on the current text, not your memory of it.

If you have already started exploring before reading this file, STOP. Discard all prior results from that exploration. Re-read this file. Then restart from the Mandatory Checkpoint.

## Tool Inventory

These are the allowed tools for this skill. Use ONLY these names and forms. Do not abbreviate, alias, or fabricate alternatives.

## Trace Interpretation

Program-emitted transcript labels such as `Explored` may appear even when they are not directly controllable by the model.

A compliant run is judged by the controllable retrieval behavior: scope choice, tool choice, file choice, line-window discipline, and whether exploration widens after the question is already answered.

Do not fail a run solely because the UI rendered `Explored` or another wrapper label.

For `exact-anchor`, the canonical first retrieval action is:

```bash
rg -n --fixed-strings -- 'ANCHOR' 'narrow/path/'
```

If the transcript does not expose the underlying command, audit the first retrievable action using the best available evidence: the stated scope, the next named file, and whether the run jumped to a broader directory than the question required.

### Bash

Use Bash directly for narrow text lookup and precise line extraction.

```bash
rg -n --fixed-strings -- 'ANCHOR_TEXT' 'target/directory/'
sed -n '120,170p' 'path/to/file.tsx'
```

`sed -n` is allowed only for a tight line window in a known file. It is not a substitute for whole-file browsing.

Default `sed -n` windows must stay within 40 lines total and should be centered on the matched line when possible. Going beyond 60 lines requires an explicit internal justification in the stop-check.

### ast-grep

| Callable | Role | Parameters |
|----------|------|------------|
| `mcp__ast_grep__find_code` | Structural pattern search across a project | `pattern` (string), `project_folder` (absolute path), `language?`, `max_results?`, `output_format?` |
| `mcp__ast_grep__find_code_by_rule` | YAML rule-based structural search | `yaml` (string, must contain id + language + rule), `project_folder`, `max_results?`, `output_format?` |
| `mcp__ast_grep__dump_syntax_tree` | Dump syntax tree of a code snippet | `code` (string), `language` (string), `format?` ("pattern" / "ast" / "cst") |
| `mcp__ast_grep__test_match_code_rule` | Test whether a YAML rule matches a code snippet | `code` (string), `yaml` (string) |

Supported languages: bash, c, cpp, csharp, css, elixir, go, haskell, html, java, javascript, json, jsx, kotlin, lua, nix, php, python, ruby, rust, scala, solidity, swift, tsx, typescript, yaml.

### LSP (language-server)

**Setup requirement:** Before any LSP query, you MUST call `mcp__language_server__start_server` with `language_id` and `project`. Get the project name from `mcp__language_server__get_server_projects` if unknown.

**LSP parameters use zero-based line and character numbers.** If `rg -n` returns line 284, the LSP `line` parameter is 283.

Navigation tools (read-only, allowed in this skill):

| Callable | Role |
|----------|------|
| `mcp__language_server__get_symbol_definitions` | Go to definition. Params: `file_path`, `line`, `character` |
| `mcp__language_server__get_symbol_references` | Find all references. Params: `file_path`, `line`, `character`, `include_declaration?` |
| `mcp__language_server__get_implementations` | Find implementations. Params: `file_path`, `line`, `character` |
| `mcp__language_server__get_call_hierarchy` | Get call hierarchy item. Params: `file_path`, `line`, `character` |
| `mcp__language_server__get_incoming_calls` | Who calls this? Params: `item` (from `get_call_hierarchy`) |
| `mcp__language_server__get_outgoing_calls` | What does this call? Params: `item` (from `get_call_hierarchy`) |
| `mcp__language_server__get_hover` | Type info at cursor. Params: `file_path`, `line`, `character` |
| `mcp__language_server__get_project_symbols` | Search symbols in project. Params: `project`, `language_id`, `query?`, `limit?`, `offset?` |
| `mcp__language_server__get_symbols` | List symbols in a file. Params: `file_path`, `limit?`, `offset?` |
| `mcp__language_server__get_type_definitions` | Go to type definition. Params: `file_path`, `line`, `character` |

**Forbidden LSP tools within this skill:** `get_symbol_renames`, `get_code_actions`, `get_code_resolves`, `get_format`, `get_range_format`, `get_completions`, `get_linked_editing_range` — these are mutating or editing-oriented.

## Enforcement

This skill is a hard contract. Every rule below is mandatory — not advisory, not "best practice".

**Violation examples that MUST NOT happen:**

- Making a tool call before completing the Mandatory Checkpoint
- Running multiple search variants in parallel "just to be safe"
- Adding "one more confirmation" search after the question is answered
- Saying "let me also check…" when the scoped question already has an answer
- Choosing a retrieval path that cannot be reduced to one of the allowed tools in this file
- Using `Read` to read source code files instead of a precise `sed -n` line window

If you catch yourself about to do any of the above, STOP. Re-read the classification and scope lock. Proceed only on the prescribed tool path.

## Mandatory Checkpoint

**You MUST complete this checkpoint internally before your first tool call. No exceptions.**

Resolve each field below in your reasoning. Do NOT output the checkpoint to the user — it is an internal planning step only.

```
CHECKPOINT (internal, do not display):
- class: [exact-anchor | semantic-search | structural-search | flow-explanation]
- target: [exact scope — file, directory, symbol, or service]
- excluded: [what is out of scope]
- question: [single question to answer]
- tool-path: [ordered list of at most 3 calls, using exact tool names from this file]
- stop-when: [concrete condition that means "done"]
```

Rules for filling this checkpoint:

1. If the user gave a visible label, constant name, function name, error text, selector, or event name → class is `exact-anchor`. Period.
2. `target` must be the narrowest possible scope. One directory, one file, one symbol — not "the app" or "the codebase".
3. `tool-path` has a hard maximum of **3 planned calls**. Each call must use an exact tool name from this skill (`rg -n`, `sed -n`, `mcp__ast_grep__*`, or `mcp__language_server__*`). If you think you need more, your scope is too wide — narrow it first.
4. `stop-when` must be a binary-testable condition, not "when I understand enough".

Planned path and recovery are different:
- The main planned path may contain at most 3 calls.
- A 4th call is allowed only as single-step recovery after a concrete failed or insufficient prior result.
- Do not pre-plan a 4-call path.

## Core Rules

Apply these rules in strict priority order. Higher rules override lower ones.

1. **Classify first, always.** Decide the classification before any tool call. If the user asked multiple questions, reduce to the first unresolved question.
2. **Lock minimum scope.** Treat user-specified boundaries as hard filters. Scope must be the smallest surface that can answer the classified question.
3. **NEVER widen scope.** Not for corroboration. Not for extra confidence. Not for "completeness". If one environment is in scope, do not inspect another. If one file answers the question, do not fan out.
4. **One gap, one expansion.** If the scoped target is insufficient, name the exact remaining gap in one sentence, then make exactly one narrowly justified scope expansion.
5. **No out-of-scope findings in the answer** unless: the user explicitly asked for comparison, the finding is the direct blocker, or the finding is the exact source of a contradiction inside the scoped target.
6. **Use exact tool names.** Do not abbreviate, alias, or fabricate tool names. Do not guess parameter names or shapes — use only the commands and callables listed in Tool Inventory.
7. **Follow the prescribed tool path** for the classification. Do not improvise.
8. **One primary tool per question.** Choose one tool. Use it. Do not run parallel alternatives.
9. **At most one follow-up call** for one explicit remaining gap. State the gap before making the call.
10. **Stop when `stop-when` is satisfied.** Do not continue exploring.

## Tool Budget

**Hard limit: 4 tool calls maximum per user question.**

- 1 call for primary lookup
- 1 call for extraction/confirmation
- 1 call for one explicit gap
- 1 call reserved for recovery if a prior call returned bad results

If you reach 4 calls and the question is not answered, STOP and report what you found and what gap remains. Do not make a 5th call.

The 4th call is recovery only. It is not part of the normal exploration path and must not be planned in advance.

Count every tool invocation: each `mcp__ast_grep__*`, each `mcp__language_server__*` call, each `rg -n`, and each `sed -n`. Parallel calls in one message each count as separate calls. LSP `start_server` counts as a call.

## Tool Roles

| Tool | When to use | NOT for |
|------|------------|---------|
| `rg -n` via Bash | Exact-anchor lookup. **Always first for `exact-anchor` class.** Use `--fixed-strings` for literal text. | Broad concept search when you have no anchor |
| `sed -n` via Bash | Pull a tight line window from a known file after another tool identified the location | First-pass discovery; reading entire files |
| `mcp__ast_grep__find_code` | Structural pattern search when you know the code shape but not the symbol name | Replacement for semantic search; first step for exact-anchor |
| `mcp__ast_grep__find_code_by_rule` | Complex structural search requiring YAML rules (multi-condition matches) | Simple text lookup |
| `mcp__language_server__get_project_symbols` | Symbol-oriented discovery when the user gave a likely symbol or partial symbol | Generic behavior search with no symbol clue |
| `mcp__language_server__get_symbol_references` | Find all callers/usages of a known symbol at a known location | Discovery when file/line is unknown |
| `mcp__language_server__get_symbol_definitions` | Jump to definition from a usage site | Browsing without a cursor position |
| `mcp__language_server__get_call_hierarchy` + `get_incoming_calls`/`get_outgoing_calls` | Trace call chains | First-pass discovery |

**Forbidden tools within this skill:**

- `Read` (full-file read tool) — NEVER use to read source code files. It pulls the entire file, wasting tokens when you already have a line number. Use a precise `sed -n` line window instead.
- `cat`, `head`, `tail`, `sed` (except `sed -n` under Shell Fallback), `ls`, `find` (except for filename discovery under Shell Fallback)
- Any intentionally chosen generic search/explore wrapper when a precise allowed tool is available. Audit this only when the underlying tool selection is actually known.
- Broad `sed -n '1,220p'` whole-file browsing when a narrower line window is available
- Mutating LSP tools listed in the Forbidden LSP section above

## Classification

Classify into exactly one type. Use this precedence when ambiguous:

1. `exact-anchor` — user gave searchable text (label, function name, constant, error, selector)
2. `flow-explanation` — user wants a call chain, calculation path, or business flow explained
3. `semantic-search` — user describes behavior/concept without a stable symbol name
4. `structural-search` — no anchor, but the code shape is guessable

### `exact-anchor`

**First tool MUST be `rg -n --fixed-strings` via Bash, scoped to the narrowest relevant directory.**

Do not start with `sed -n`, `mcp__ast_grep__find_code`, or LSP. Do not search multiple spelling variants in parallel.

Directory choice is part of the contract:
- If the user gave a functional area such as `classroom`, `billing`, or `auth`, start in the directory that directly matches that area.
- Do not start from `app/`, `.`, or the repo root unless the user explicitly asked for cross-surface comparison or the area-specific directory truly does not exist.
- If both `app/feature/` and `components/feature/` exist, choose the one that best matches the asked artifact first. For visible UI text, prefer the UI component directory before route files unless the user explicitly asked about routing.

Sequence:
1. `rg -n --fixed-strings -- 'ANCHOR' 'target/dir/'` via Bash → locate file and line
2. If the line answers the question → STOP
3. If you need the implementation body → `sed -n` on a tight window in the matched file
4. If the user also asked "who uses it" → `mcp__language_server__get_symbol_references` (if LSP is started) or one more scoped `rg -n` via Bash

After step 1, stay anchored to the matched file. Do not invent new symbol names to search for.

Example:
- Question: "Where is `View Details` handled in classroom?"
- Allowed: `rg -n --fixed-strings -- 'View Details' 'components/classroom/'` → `sed -n` on the matched file and nearby lines → answer
- Forbidden: after seeing the click handler body, searching `handleCardClick`, page entry files, backend handlers, or the "full chain" unless that exact gap is still unresolved inside the scoped file

### `semantic-search`

Use `semantic-search` only when no stable visible text, selector, constant, or function name exists.

Do not use `semantic-search` when the request already contains an exact anchor. That is an `exact-anchor` task, even if the surrounding behavior is still unclear.

Prefer tool choice in this order:
1. If the clue is symbol-like, use `mcp__language_server__get_project_symbols`
2. If the clue is code-shape-like, use `mcp__ast_grep__find_code`
3. Use one scoped `rg -n` query only when the clue is textual behavior and no better symbol or structure clue exists

Sequence:
1. `mcp__language_server__get_project_symbols`, `mcp__ast_grep__find_code`, or one scoped `rg -n` → get candidates
2. If top hit identifies the right file/symbol → `sed -n` to read the relevant line window
3. If still ambiguous → one other allowed disambiguator from the list above
4. STOP

### `structural-search`

First tool is `mcp__ast_grep__find_code` (or `mcp__ast_grep__find_code_by_rule` for complex patterns).

Sequence:
1. `mcp__ast_grep__find_code` → find pattern matches
2. `sed -n` for the best candidate's line window
3. STOP or fill one explicit gap

### `flow-explanation`

Locate the entry point first:
- If user gave an exact anchor → `rg -n --fixed-strings` via Bash (treat as exact-anchor for the first step)
- If naming is weak but symbol-like → `mcp__language_server__get_project_symbols`
- If naming is weak and text-like → one scoped `rg -n`
- If the code shape is known → `mcp__ast_grep__find_code`

Then explain only the main flow. Not every consumer. Not storage layers. Not adjacent flows.

Sequence:
1. Locate entry point (method above)
2. `sed -n` for the main function body or relevant line window
3. For the main caller: `mcp__language_server__get_incoming_calls` (requires `get_call_hierarchy` first, counts as 2 calls) OR `rg -n` via Bash for the symbol name (1 call)
4. STOP and explain

For "who calls X":
1. `rg -n` via Bash to locate X → get file and line
2. `mcp__language_server__get_call_hierarchy` + `mcp__language_server__get_incoming_calls` (2 calls) OR `rg -n` via Bash for the function name across the project (1 call)
3. STOP

For "what does X call":
1. `sed -n` for the symbol body
2. If one outgoing edge matters → `rg -n` via Bash or `mcp__language_server__get_outgoing_calls` to confirm
3. STOP

## Shell Rules

`rg -n` via Bash is the **primary tool for `exact-anchor` lookup**. `sed -n` is the only allowed shell tool for reading source lines, and only after another tool has already identified the file and line window.

When shell is used for text search:

**ALWAYS use `--fixed-strings` for literal text lookup.** This prevents regex interpretation and variable expansion.

**ALWAYS single-quote the pattern and path separately.** Never interpolate them into a larger fragment.

**Correct examples:**

```bash
# Literal text search — safe
rg -n --fixed-strings -- 'View Details' 'components/classroom/'

# Path with brackets — safe
rg -n --fixed-strings -- 'fetchStudents' 'app/teacher/my-classes/[classCode]/page.tsx'

# Regex search — only when explicitly needed, stated as regex
rg -n 'handleClick|onClick' 'components/classroom/'

# Tight line-window extraction — safe
sed -n '260,290p' 'components/classroom/teacher-classroom-card.tsx'
```

**WRONG — never do these:**

```bash
# WRONG: unquoted path with brackets → shell glob expansion
rg -n "pattern" app/teacher/my-classes/[classCode]/page.tsx

# WRONG: pattern with ${} → shell variable expansion
rg -n "fetch(`/api/classrooms/${classCode}/`)" path

# WRONG: multiple unrelated patterns "just in case"
rg -n "view details|view-details|view_details|ViewDetails" .

# WRONG: whole-file browsing disguised as extraction
sed -n '1,240p' 'components/classroom/teacher-classroom-card.tsx'
```

**If a shell command fails with expansion or globbing error:**
1. This is a command-construction failure, not a search miss
2. Fix quoting. Do not switch tools or widen scope
3. Re-run the same scoped query with correct construction

## Structured Result Recovery

A structured result is suspect if:
- The symbol is ambiguous
- The snippet or line window is clearly the wrong body
- The location contradicts the layer being investigated
- The selected line window is empty or obviously truncated

Recovery — in this order, choosing exactly one:
1. Narrow the question (not the tool)
2. If really `exact-anchor` → tighter `rg -n --fixed-strings` via Bash with narrower path
3. If really `semantic-search` and the clue is symbol-like → one `mcp__language_server__get_project_symbols` call
4. If really `semantic-search` and the clue is code-shape-like → one `mcp__ast_grep__find_code` call
5. If really `semantic-search` and only textual behavior remains → one narrower scoped `rg -n` call
6. If really `structural-search` → one more `mcp__ast_grep__find_code` call
7. If the location is known but the read window is wrong → one corrected `sed -n` call on the same file
8. Shell fallback only if MCP tools are failing entirely

Do not jump from one suspect result into multiple new tools. Do not treat a failed extraction as justification to broaden the query — correct the target first.

## Stop Rule

**Answer the scoped question only.** Use the minimum complete answer, not the maximum complete map.

Do not append: comparisons, neighboring systems, extra context, alternative entry points, "while we're here" observations, or "for completeness" additions.

For explanation requests, stop when you can state:
1. The main function or entry point
2. The relevant inputs or triggering conditions
3. The key transformation, decision, or branch logic
4. The main caller or entry path (when relevant)

**Before every tool call after the first, you MUST evaluate this internally (do not display to the user):**

```
STOP-CHECK (internal, do not display):
[stop-when condition] → [met | not-met] → [STOP | call N of 4: <what and why>]
```

- If `met` → STOP immediately. Compose your answer. Do not make another call.
- If `not-met` → proceed with the next call, tracking the call number (2 of 4, 3 of 4, etc.).
- If you are about to make call 4 of 4 and stop-when is still not met, this call is your last. Plan accordingly.

**Skipping this evaluation is a skill violation.** The discipline must happen even though the output is silent.

## Anti-Patterns

These are explicit violations. If you find yourself doing any of these, you have broken the skill contract:

| Anti-pattern | Why it's wrong |
|-------------|---------------|
| Searching 3 spelling variants in parallel | Violates one-primary-tool rule and minimum scope |
| "Let me also check if there's another entry point" | Widening scope for confidence (Rule 3) |
| "补一层后端接口确认完整链路" | Exploring beyond the scoped question |
| Making 5+ tool calls for one question | Exceeds tool budget |
| Repeatedly changing `sed -n` windows without first narrowing the question | Should narrow the question, not retry blindly |
| Outputting intermediate narration between every tool call | Slows execution; state findings only at the end |
| Running `rg` via Bash with unquoted `${variable}` in the pattern | Shell expansion — use `--fixed-strings` and single quotes |
| Using `Read` to consume an entire source file | Wastes tokens; use a precise `sed -n` window instead |
| Starting with `sed -n` before any locator tool identified the file and line | Skips classification and anchor discovery |
| Running `sed -n '1,220p'` as a default first read | Whole-file browsing is out of scope |
| Treating `Explored` itself as proof of compliance or proof of violation | Program labels are not enough; audit the controllable retrieval behavior |
| Falling back to broad `rg -n` in `semantic-search` when the clue is already symbol-like | Skips the more precise disambiguator and widens noise |

## Failure Rubric

Treat each case below as a failed run of this skill, even if the answer text is partially or fully correct:

- The first retrievable action for an `exact-anchor` question was broader than a narrow `rg -n --fixed-strings` lookup
- The run starts in `app/`, `.`, or repo root even though the user already named a narrower functional area
- The run uses `Read` on a source file instead of a narrow `sed -n` window
- The run hits the requested anchor, then expands into route files, backend files, or adjacent entry points without an unresolved gap inside the matched file
- The final answer is correct but the trace violates any hard rule above
