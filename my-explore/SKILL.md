---
name: my-explore
description: Use when doing any code task in Codex that requires search, find, trace, explain, read, or analyze work before answering or editing.
---

# Code Navigation

In Codex, these tools are provided by the session tool inventory. They are not loaded with a separate Skill tool call or MCP resource-discovery step.

Use these tool families directly by their exact tool names:

1. `mcp__ast_grep__*` for structural code search
2. `mcp__probe__*` for semantic search and code extraction
3. `mcp__language_server__*` for symbol, reference, and type navigation

Codex rule:
- If a needed tool is present in the session tools, call it directly.
- If a needed tool is not present in the session tools, treat it as unavailable and continue with the allowed fallback path in this skill.
- Do NOT make separate "tool loading", "resource listing", or "template listing" calls before exploration.

## Allowed exploration tools only

Skill-file reads are allowed.

For source-code exploration in this skill, use only:
- `rg -n`
- `mcp__probe__search_code`
- `mcp__probe__extract_code`
- `mcp__ast_grep__find_code`
- `mcp__ast_grep__find_code_by_rule`
- `mcp__ast_grep__dump_syntax_tree`
- `mcp__ast_grep__test_match_code_rule`
- `mcp__language_server__get_server_status`
- `mcp__language_server__get_server_projects`
- `mcp__language_server__start_server`
- `mcp__language_server__get_project_symbols`
- `mcp__language_server__get_symbol_definitions`
- `mcp__language_server__get_symbol_references`
- `mcp__language_server__get_call_hierarchy`
- `mcp__language_server__get_incoming_calls`
- `mcp__language_server__get_outgoing_calls`
- `mcp__language_server__get_hover`
- `mcp__language_server__get_type_definitions`

For source-code exploration in this skill, do NOT use:
- built-in `Search`
- built-in `Read`
- `rg --files`
- ad hoc shell listing commands such as `find` or `ls`
- broad shell file reads such as `cat`, `head`, or `tail`

Once code exploration starts, stay on this tool whitelist.

## Exact tool usage in Codex

| Tool | Use when | Required inputs | Correct usage | After a hit |
|------|----------|-----------------|---------------|-------------|
| `mcp__probe__search_code` | You need semantic discovery, symbol discovery after exact text lookup misses, or a fallback when literal text lookup is unsuitable | `path` must be the absolute project root. `query` must use valid Elastic-style syntax. | Do NOT use this as the default first step for a known text anchor. For exact symbol lookup, set `exact: true`. Quote camelCase, PascalCase, and snake_case exact terms inside `query`, for example `"CreateClassDialog"`. If `strictElasticSyntax: true`, use explicit operators such as `AND` and `OR`, and keep exact terms quoted. Prefer one primary anchor first. Do not start by combining several anchors unless the task truly requires an intersection query. | Switch to `mcp__probe__extract_code` with the returned `file:line` or `file#symbol`. Do not continue broad search after you already have the location. |
| `mcp__probe__extract_code` | You already have `file:line` or `file#symbol` and need the actual implementation | `path` must be the absolute project root. `files` must contain absolute paths, each optionally suffixed with `:line` or `#symbol`. | Prefer `file#symbol` when the symbol is known. If `#symbol` returns only a thin wrapper or the wrong node, retry with `file:line`. Use `lsp: true` only when you need call hierarchy, references, or enhanced symbol data. Batch multiple callees or callers in one `files` array when tracing. | Answer the question if the extracted code is sufficient. Otherwise trace only the direct caller or callee that still matters. |
| `mcp__ast_grep__find_code` | You know the code shape but not the exact symbol name | `pattern` must be a valid AST pattern. `project_folder` must be an absolute path. | Use this for structural search, not for plain text lookup. Set `language` when it helps disambiguate parsing. Do not write grep-style regex in `pattern`; write a valid code pattern instead. | Extract the best match with `mcp__probe__extract_code`. |
| `mcp__ast_grep__find_code_by_rule` | You need a relational structural query such as `inside`, `has`, or `follows` | `yaml` must contain `id`, `language`, and `rule`. `project_folder` must be an absolute path. | Use this when `find_code` is too simple. For relational rules, prefer `stopBy: end` so traversal does not stop too early. Test and tighten the rule before widening scope. | Extract the best match with `mcp__probe__extract_code`. |
| `mcp__language_server__get_server_status` | You need LSP navigation and must know whether a server is already running | none | Use this before LSP navigation if server state is unknown. If the needed server is stopped, use `mcp__language_server__get_server_projects`, then `mcp__language_server__start_server`. | Once the server is running, switch to the specific LSP navigation call you actually need. |
| `mcp__language_server__get_symbol_definitions` | You have a usage site and need the definition | `file_path`, `line`, `character` | LSP positions are zero-based. If another tool showed line 214, pass `line: 213`. Use this only after you already know the usage location. | Read or extract the definition site, then stop or continue tracing from there. |
| `mcp__language_server__get_symbol_references` | You know the symbol location and need usages | `file_path`, `line`, `character` | Use this only after you have the exact symbol location. Set `include_declaration` only when the declaration site matters to the question. | Trace only the relevant callers or usage sites. |
| `mcp__language_server__get_call_hierarchy` plus `mcp__language_server__get_incoming_calls` or `mcp__language_server__get_outgoing_calls` | You need who-calls-this or what-does-this-call | `file_path`, `line`, `character` for `get_call_hierarchy`, then `item` for incoming or outgoing calls | Use call hierarchy only after the entry symbol is known. Do not use it as a first-pass discovery tool. | Extract the returned caller or callee locations directly instead of going back to broad search. |
| `mcp__language_server__get_project_symbols` | You have a symbol-shaped clue but not a file location | `project`, `language_id` | Use this for symbol discovery when a name is likely but not yet located. It is stronger than broad semantic search when the clue is already symbol-like. | Once the symbol location is identified, switch to `extract_code` or another exact LSP navigation call. |
| `mcp__language_server__get_hover` or `mcp__language_server__get_type_definitions` | You need type or interface context at a known location | `file_path`, `line`, `character` | Use these only after the code location is known. They are context tools, not first-pass discovery tools. | Return to the main trace only if the type information answers an explicit gap. |

Within this skill, do NOT use editing-oriented LSP tools such as `get_symbol_renames`, `get_code_actions`, `get_code_resolves`, `get_format`, `get_range_format`, `get_completions`, or `get_linked_editing_range`.

## First-call routing

Choose the first code-exploration call by the task shape:

| Situation | First call | Do not do first |
|-----------|------------|-----------------|
| Known text anchor such as a component name, function name, constant, route string, or UI label | `rg -n --fixed-strings -- 'ANCHOR' 'scoped/path/'` | `mcp__probe__search_code` |
| Symbol-like clue but no stable literal anchor | `mcp__probe__search_code` or `mcp__language_server__get_project_symbols` | broad shell search |
| Known code shape | `mcp__ast_grep__find_code` or `mcp__ast_grep__find_code_by_rule` | grep-style regex in `pattern` |
| Known file and known handler or method inside that file | `rg -n --fixed-strings -- 'HANDLER_NAME' 'known/file.tsx'` or `mcp__probe__extract_code` from an already known line | broad project search |

If a known text anchor exists, the first call is `rg -n --fixed-strings`. Only fall back to `mcp__probe__search_code` if that exact text lookup misses or if the task is not truly literal-text lookup.

## Fallback and stop rules

- Once you have a relevant `file:line` or `file#symbol`, switch to `mcp__probe__extract_code`.
- Once the direct handler body is known, do NOT go back to broad search to guess route strings, callback names, or helper names.
- Trace only direct callers or direct callees that appear in the extracted code or returned LSP data.
- If `mcp__probe__search_code` returns no results for a known text anchor, fall back to `rg -n --fixed-strings`, not another broader semantic search.
- If a shell fallback path contains `(`, `)`, `[`, `]`, `*`, or `?`, quote the full path.

## Classify FIRST — BEFORE any tool call

You MUST classify and Read the corresponding file BEFORE making any search/read/extract call:

| Type | Signal | File to Read |
|------|--------|-------------|
| **Pinpoint** | Component/function name or UI label known | `pinpoint.md` |
| **Trace** | How data/control flows across files | `trace.md` |
| **Discovery** | No specific symbol known, only abstract concepts | `discovery.md` |
| **Structural** | Find all code matching an AST pattern | `structural.md` |

Read the file, then follow its steps and tool rules exactly. After each tool call: answer found? -> stop.

## Tool preference (fallback when classification files are not loaded)

`rg` is ONLY for the first lookup when you have a known literal text anchor. Once you have `file:line`, switch to MCP tools:

| Once you have file:line, use | NEVER do this instead | Returns → next action |
|---|---|---|
| `mcp__probe__extract_code` with `file#symbol` or `file:line` | `cat` / `head` / `tail` / built-in `Read` on entire file | complete function/class body → read the output to answer the question or decide what to trace next |
| `mcp__probe__extract_code` with `lsp: true` | separate `rg` calls to find callees | code body + call hierarchy + references → callee file:line and caller file:line are in the output, extract them directly |
| `mcp__probe__search_code` with `exact: false` | `rg` when the name is unknown or fuzzy | file:line candidates ranked by relevance → extract the top match |
| `mcp__probe__search_code` with `exact: true` | `rg` for exact symbol name | file:line of exact symbol → extract to read implementation |
| `mcp__ast_grep__find_code` | `rg` with regex patterns | file:line of structural matches → extract to read, no false positives |
| `mcp__ast_grep__find_code_by_rule` | `find_code` for complex patterns | file:line filtered by `inside`/`has`/`follows` → extract to read |
| `mcp__language_server__get_symbol_references` / `get_symbol_definitions` | manual import tracing with `rg` | dependency map → identify who depends on what |
| Batch multiple files in one `files` array | one `mcp__probe__extract_code` call per file | combine multiple file:line into one call to reduce total tool calls |

**After the first `rg` hit gives you a file:line, do NOT use `rg` again to find callees, callbacks, or downstream functions.** Use `mcp__probe__extract_code` (with `lsp: true` if available) and read the returned code body and hierarchy data.

**NEVER use `cat`, `head`, `tail`, `sed`, built-in `Search`, or built-in `Read` for source-code exploration** — use the allowed tool whitelist above.
