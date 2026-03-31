---
name: my-explore
description: Code navigation methodology using CodeGraph + CocoIndex + LSP. Invoke before any code exploration to load navigation rules and tool usage.
---

# Code Navigation: CodeGraph + CocoIndex + LSP

## Overview

Six tools, each for a distinct purpose. Select the right one per question — do not invoke multiple tools for the same question.

| Purpose | Tool | What it gives you |
|---------|------|-------------------|
| **Structure** — symbol relationships, dependency graph | **CodeGraph** (`context`, `node`, `callers`, `callees`, `impact`) | Entry points, signatures, code snippets, dependency edges |
| **Symbol name search** — find symbols by partial name | **CodeGraph** (`search`) | Symbol locations (no code); use when you know part of the name but not the exact symbol |
| **Discovery** — find code by meaning | **CocoIndex** | Code chunks with file paths, line numbers, relevance scores |
| **Precision** — definitions, references, callers, types, implementations | **LSP** | Language-server-level analysis; requires a file position from a previous result |
| **Literal search** — find exact text patterns | **Grep** | Lines matching a regex, scoped to a directory |
| **File discovery** — find files by name pattern | **Glob** / **codegraph_files** | File paths matching a glob pattern or indexed tree view |

## Tool selection — one tool per question

Before calling any tool, classify the question and select **exactly one** tool. Do not invoke multiple tools for the same question.

| Question type | Tool | Rationale |
|--------------|------|-----------|
| All occurrences of a known keyword in a directory (constant name, function name, import path) | **Grep** with `path` scoped to target directory | Exact text match; highest precision when the keyword is known |
| Find code by concept when you do not know the exact keywords or location (e.g., "error handling logic", "permission checks", "file upload flow") | **cocoindex search** with `paths` narrowed when the target directory is known; omit `paths` for codebase-wide search | Semantic similarity; finds relevant code by meaning, not literal text |
| What calls a function / what a function calls (file position known) | **LSP incomingCalls** / **LSP outgoingCalls** | Language-server analysis; resolves through aliases, generics, and re-exports |
| What calls a symbol / what a symbol calls / what breaks if a symbol changes (only symbol name known, no position) | **codegraph_callers** / **codegraph_callees** / **codegraph_impact** | Index-based lookup by name; use when file position is unavailable |
| Jump to where a symbol is defined (file position known) | **LSP goToDefinition** | Language-server analysis; follows through re-exports and aliases |
| Find implementations of an interface or abstract method | **LSP goToImplementation** | Returns concrete implementations; no equivalent in CodeGraph |
| Implementation body of a single named function, class, or constant (only symbol name known, no position) | **codegraph_node(includeCode: true)** | Index-based lookup by name; use when file position is unavailable |
| Discover symbols matching a partial name (e.g., know "schema" but not the full symbol name) | **codegraph_search** | Returns symbol locations (no code) by name pattern; use `kind` filter to narrow by type. Follow up with `codegraph_node` to read the matched symbol's code |
| Entry-point symbols and relationships for a task described in natural language | **codegraph_context** | Returns signatures, snippets, and dependency edges matching a task description |
| Every file that references a symbol across the entire codebase | **LSP findReferences** | Exhaustive reference list from the language server |
| Resolved type at a specific source position | **LSP hover** | Returns the exact type the type system resolves at that position |
| All symbols exported or defined in a single file | **LSP documentSymbol** | Symbol list with kinds (function, class, variable, etc.) — use instead of Read for file overview |

Parallel calls are permitted only when they answer **independent** questions. Two calls answering the same question waste tokens.

## LSP vs CodeGraph — when both can answer the question

Several operations overlap between LSP and CodeGraph. When both can answer the question, use this priority rule:

- **File position known** (filePath + line + character from a previous result) → use **LSP**. It uses language-server analysis and is more accurate.
- **Only symbol name known** (no file position) → use **CodeGraph**. It can look up symbols by name without a position.

| Operation | LSP (position required) | CodeGraph (name only) |
|-----------|------------------------|----------------------|
| Find callers | `incomingCalls` | `codegraph_callers` |
| Find callees | `outgoingCalls` | `codegraph_callees` |
| Navigate to definition | `goToDefinition` (returns file location) | `codegraph_node` (returns source code) |

Note: `goToDefinition` returns a file position; `codegraph_node` returns the actual source code. They serve different purposes — use `goToDefinition` to locate, `codegraph_node(includeCode: true)` to read the body.

## Tool limitations

Each tool has a blind spot. Selecting the wrong tool produces noise or misses results:

| Tool | What it cannot do |
|------|-------------------|
| **codegraph_context** | Cannot filter by directory. Typically returns only 1–2 code layers (e.g., repo + entity) and misses others (controller, service, interfaces, validation). Use as a starting point, not a complete picture. Do not use it for "list everything under directory X" queries. |
| **cocoindex search** | Cannot guarantee exact string matches. It uses embedding similarity, so it may miss a literal string that Grep finds instantly. |
| **Grep** | Cannot understand meaning. It matches character patterns, not concepts. Unusable when you do not know the keyword. |
| **codegraph_search** | Cannot return code — only symbol names and locations. Cannot do semantic/concept search — it matches symbol names only. Use `cocoindex search` for concept-based discovery, `Grep` for literal text search. |
| **codegraph_node** | Cannot discover multiple symbols at once. It returns one symbol per call. |
| **codegraph_callers** | Cannot detect JSX usage. React components are rendered via `<Component />`, not called as `Component()`. `codegraph_callers` only tracks function calls, so it returns empty for components. Use `codegraph_search` (which shows import references) or `LSP findReferences` to find where a component is used. |
| **LSP** (all operations) | Cannot operate without a file position (filePath + line + character). Always requires a previous result that provides the position. Cannot be used as the first tool when only a symbol name is known. |

## Parameter guidelines

### codegraph_context `task`

The `task` string should address three elements:

1. **Specific action** — state what to find, not the high-level objective. Write `"list all database query functions and their SQL strings"`, not `"understand the data layer"`.
2. **Full directory path** — include the exact path when the scope is a subdirectory: `"inside src/modules/billing"`. This serves as a relevance hint, not a hard filter (see Tool limitations).
3. **Symbol names when known** — name the functions or constants you expect to appear: `"createInvoice, updateSubscription"`.

### cocoindex search

**Precision strategy** — cocoindex returns code by semantic similarity, not exact match. Precision depends on query construction:

1. **Decompose by layer**: Split one broad query into 2–3 focused queries, each scoped to a specific code layer with `paths`:
   ```
   BAD:  query: "star graph clone service repository controller schema"  limit: 20
         — mixes all layers; top results dominated by test files, implementation gets pushed out

   GOOD: query: "clone star graph service implementation"    paths: ["src/application/*", "src/controllers/*"]  limit: 10
         query: "star graph repository schema model"         paths: ["src/infrastructure/*"]                    limit: 10
         — each query targets one layer; results are focused
   ```

2. **Exclude test files when exploring implementation**: Use `paths` to scope to `src/*` when you need implementation code, not test patterns.

3. **Score threshold**: Results below **0.45** are usually noise. Stop processing when scores drop below this threshold — do not read all results just because `limit` allows more.

4. **Extract, then deepen**: cocoindex returns code **chunks** (partial files), not complete symbol bodies. After identifying relevant symbols from chunks, use `codegraph_node(includeCode: true)` to get the complete implementation.

**`paths` filter rules**:

```
BAD:  paths: ["src/**"]                      — too broad; no filtering value
GOOD: paths: ["src/modules/billing/*"]       — targets only the billing module
GOOD: (omit paths)                           — codebase-wide concept search when scope is unknown
```

### Grep `path`

Always pass the `path` argument scoped to the target directory:

```
Grep(pattern: "createInvoice|updateSubscription", path: "src/modules/billing")
```

## Workflow

### 1. Load tool schemas

Run `ToolSearch("codegraph")`, `ToolSearch("cocoindex")`, and `ToolSearch("LSP")` to load tool schemas. If a ToolSearch returns no results, that tool is unavailable — skip it in all subsequent steps.

### 2. Initial exploration (for feature/task-level understanding)

When exploring a feature or task (not a single specific question), use this starting strategy:

**If cocoindex is available** (preferred — returns code chunks with file paths and line numbers across multiple layers):

1. Decompose the task into 2–3 focused queries by layer (see **cocoindex search** parameter guidelines)
2. From results, extract: symbol names, file paths, line numbers
3. Use `codegraph_node(includeCode: true)` only for symbols where the cocoindex chunk was incomplete (truncated class, partial function)
4. Use `LSP` for type precision when cocoindex results show interfaces or generics that need resolution

**If cocoindex is unavailable** (fallback):

1. Start with `codegraph_context` — describe the task with specific action, directory hints, and known symbol names
2. Expect partial coverage (codegraph_context typically returns only 1–2 layers). Identify which layers are missing from the results.
3. Fill missing layers with `codegraph_node(includeCode: true)` for individual symbols

### 2b. Single question

For a single specific question (not broad exploration), consult the **Tool selection** table. Classify your question, pick the single best tool, apply the **Parameter guidelines**, and make the call. If no row matches, use the **Overview** table to identify the right tool category.

After results return, assess whether the accumulated information answers the original question. If yes, **stop**.

### 3. Fill remaining gaps

If the question is not fully answered, identify the **specific gap** — not a vague "I need more context". Then consult the Tool selection table again for the gap and make one more call.

Common follow-up patterns (use only when needed):

| Gap | Tool |
|-----|------|
| Need the file location where a symbol is defined | `LSP goToDefinition` using filePath, line, and character from the previous result |
| Need the implementation body (position unknown, only name known) | `codegraph_node(includeCode: true)` |
| Need all consumers of a symbol found in step 2 | `LSP findReferences` using the filePath and line from the previous result |
| Need what calls a function or what a function calls | `LSP incomingCalls` / `LSP outgoingCalls` using position from the previous result |
| Need concrete implementations of an interface or abstract method | `LSP goToImplementation` using position from the previous result |
| Need the exact inferred type at a position | `LSP hover` |
| Know a partial symbol name but not the exact name | `codegraph_search` with the partial name; then `codegraph_node` on matched results |
| Found a symbol name but need surrounding context | `cocoindex search` with the symbol name as query and narrow `paths` |

For all LSP operations, use `filePath` and `line` from the previous result directly. Set `character` to the column where the symbol name starts (1-based, as shown in editors).

### 4. Stop when answered

After each tool call, ask: does the accumulated information answer the original question? If yes, stop. If no, return to step 3.

## Prohibited: `Read` on source code files

**Do not use `Read` on source code files.** Use `codegraph_node(includeCode: true)` for symbol implementations, `LSP` for references and types, and `Grep` for literal strings.

**Test files** (files with `test` or `spec` in the name, e.g., `*.test.ts`, `*.spec.js`, `*_test.go`) follow the same prohibition. To understand existing test patterns:
1. Use `LSP documentSymbol` to see the test structure (describe/it blocks)
2. Use `Grep` to find specific patterns (mock setup, import conventions, assertions)
3. Only if the above are insufficient, use `Read` with a line range (e.g., `offset: 1, limit: 50`) to see a targeted section — never read the entire file without a line range

This prohibition applies only to files that contain programmatic logic. Non-code files (`.md`, `.json`, `.yaml`, `.css`, `.svg`, `.html`, `.toml`, `.env`, etc.) may be read freely with `Read`, `Glob`, or `Grep`.

## File discovery

Use `codegraph_files` to explore project structure (directories, file lists, language breakdown). Use `Glob` for files not in the CodeGraph index. Limit Glob to 3 calls maximum, each scoped to a specific directory.
