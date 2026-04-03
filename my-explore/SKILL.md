---
name: my-explore
description: Code navigation methodology. Invoke before any code exploration to load tool schemas and navigation rules.
---

# CRITICAL RULES — read before every tool call

- **Read**: ALWAYS set `offset` and `limit`. Never read an entire file. Use 30-50 lines around the target.
- **Glob for files, Grep for content.** Never use Grep to find files by path pattern — use Glob.
- **Probe is for Discovery only** — never use Probe for Pinpoint, Trace, or Structural.

# Code Navigation: Grep + ast-grep + LSP (+ Probe for Discovery)

## Load tool schemas first

```
ToolSearch("ast-grep")
ToolSearch("probe")
ToolSearch("LSP")
```

If a ToolSearch returns no results, that tool is unavailable — skip it.

## Step 1: Classify the question

| Type | Signal | Example |
|------|--------|---------|
| **Pinpoint** | Question identifies ANY of: a component name, function name, UI label/button text, or a known area + element combination | "What does the View Details button in classroom do?" / "What's in handleSubmit?" |
| **Trace** | Question asks how data or control flows across files | "How does login data reach the dashboard?" |
| **Discovery** | No component, function, or UI element is identifiable — only abstract domain concepts | "Does this project have rate limiting?" |
| **Structural** | Question asks for all code matching an AST pattern | "Find all API route handlers" |

**Default to Pinpoint.** Only use Discovery when you genuinely cannot identify any specific component, function, or UI element from the question.

## Step 2: Execute

**Pinpoint** — locate the exact code, no broad search:
1. **Find the location.** Use **Grep** with the known text scoped to the likely directory → get file:line. Remember: Grep for content, **Glob** for finding files.
2. **Read the code.** Use **Read** with `offset` and `limit` (30-50 lines around the match). Or use **ast-grep find_code** if you know the code shape.
3. If the code delegates to another function or file, use **Glob** to find the target file, then **LSP goToDefinition** or **ast-grep** to locate the code.

**Trace** — follow the call chain from entry point:
1. Pinpoint the entry point (steps above)
2. **LSP outgoingCalls** or **goToDefinition** at each hop. Read each hop with **Read** (`offset` + `limit`).
3. Summarize the full flow

**Discovery** — semantic search, then narrow:
1. **Probe search_code** with domain keywords (stemming enabled by default), scoped to likely directory
2. Once you have a concrete file or function, switch to Pinpoint or Trace
3. If Probe is unavailable, fall back to **Grep** with multiple keyword patterns

**Structural** — find all AST pattern matches:
1. **ast-grep find_code** or **find_code_by_rule**
2. Narrow with `inside`/`has` constraints if too many results

## Step 3: Stop check

After each tool call — does the result answer the question? Yes → **stop**. No → identify the gap, consult the Tool selection table for the next tool.

## Tool selection

| Need | Tool |
|------|------|
| Known text in source code | **Grep** with scoped `path` |
| Find files by path pattern | **Glob** (NOT Grep) |
| Domain keywords, location unknown | **Probe search_code** (stemming enabled by default) |
| Read code at known file:line | **Read** with `offset` and `limit` (30-50 lines) |
| All call sites of a function | **ast-grep** `funcName($$$)` |
| AST structural pattern | **ast-grep find_code_by_rule** (YAML rule with `inside`/`has`/`follows`) |
| Function body (name known) | **ast-grep** with target language syntax (e.g., JS: `function name($$$) { $$$ }`) |
| What calls / what is called (position known) | **LSP incomingCalls / outgoingCalls** |
| Jump to definition | **LSP goToDefinition** |
| Find implementations | **LSP goToImplementation** |
| All symbols in a file | **LSP documentSymbol** |
| All references to a symbol | **LSP findReferences** |
| Type at position | **LSP hover** |
| Partial name match | **Grep** with regex |

**Priority**: LSP (position known) > ast-grep (code shape known) > Grep (literal text). Probe is reserved for Discovery only.

## Tool notes

**ast-grep**: `$NAME` = one AST node, `$$$` = zero or more nodes. Write patterns in the target language's syntax. Use `dump_syntax_tree` when patterns don't match.

**Probe search_code** (Discovery only): Semantic code search. Stems and splits keywords by default — `getUserData` matches `get`, `user`, `data`. Supports ElasticSearch query syntax: `"exact phrase"`, `(error AND handler)`, `(auth OR authorization)`. Always set the `path` parameter.

## Rules

Repeated from top — these apply to EVERY tool call:

- **Read**: ALWAYS set `offset` and `limit`. Never read an entire file. 30-50 lines around the target.
- **Glob for files, Grep for content.** Never use Grep to find files by path pattern — use Glob.
- **Probe is for Discovery only.**
- **File discovery**: `Glob` (max 3 calls, each scoped to a specific directory).
