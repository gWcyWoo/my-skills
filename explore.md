# Code Navigation: CodeGraph + CocoIndex + LSP

## Tool Scope

From CodeGraph, use only: `codegraph_context`, `codegraph_node`, `codegraph_files`. From CocoIndex, use only the search tool. From LSP, use only `findReferences` and `hover`. Other loaded tools are not part of this workflow.

## Overview

Three tools, three purposes. Use them together for efficient code understanding.

| Purpose | Tool | What it gives you |
|---------|------|-------------------|
| **Structure** — symbol relationships, module graph | **CodeGraph** | Entry points, signatures, code snippets, dependency relationships |
| **Discovery** — find code by meaning | **CocoIndex** | Code chunks with file paths, line numbers, relevance scores |
| **Precision** — all consumers, exact types | **LSP** | Every reference to a symbol, resolved inferred types |

| Need | Tool | What you get |
|------|------|--------------|
| Entry-point symbols for a task | `codegraph_context` | Signatures, code snippets, relationships — often enough without further calls |
| Find code by natural language or concept | `cocoindex search` | Code chunks with content, file paths, line numbers, similarity scores |
| Symbol signature or type definition | `codegraph_node(includeCode: false)` | Interface shape, parameter/return types |
| Function/method implementation | `codegraph_node(includeCode: true)` | The symbol's body |
| All consumers of a symbol | `LSP findReferences` | Every file that references it |
| Exact inferred/generic type | `LSP hover` | Resolved type at a position |
| Project file structure | `codegraph_files` | Tree view of indexed files with metadata |
| File discovery (non-indexed) | `Glob` | Files matching a pattern |
| String content search | `Grep` | URLs, error messages, literals, config values |
| Cross-function flow in one file | `Read` (with line range) | How multiple functions in the same file interact |

## Workflow

### 1. Start with `codegraph_context`

First, run `ToolSearch("codegraph")`, `ToolSearch("cocoindex")`, and `ToolSearch("LSP")` to load tools. If a ToolSearch returns no results, that tool is unavailable — skip it.

Then describe your full task to `codegraph_context`. You get entry-point symbols with signatures, code snippets, and relationships.

**After the results come back, extract what you already have:** symbols, interface shapes, parameter/return types, data flow direction. Many of your questions are already answered here.

If you need symbols not returned by `codegraph_context`, use `cocoindex search` with a natural language description of what you're looking for. CocoIndex uses semantic similarity — you don't need exact symbol names.

```
cocoindex search(query: "resume event service handling uploaded events")
← returns code chunks with file paths, line numbers, and content
```

From the results, extract **symbol names** for step 2 (`codegraph_node`) and **filePath + line** for step 3 (`LSP findReferences`). File paths in the results are for LSP findReferences, not for Read. To see a symbol's implementation, use `codegraph_node(includeCode: true)`.

### 2. Deepen with `codegraph_node`

For symbols that need more detail than step 1 provided, pass the symbol name to `codegraph_node`:

| Symbol kind | `includeCode` | Reason |
|-------------|---------------|--------|
| interface, type, enum, constant | `false` (or omit) | Signature IS the complete definition |
| function, method, class | `true` | You need to see the implementation body |

```
cocoindex search returned code containing UploadService class

→ codegraph_node(symbol: "UploadService", includeCode: true)
← returns the class implementation
```

If the signature or code was already returned in step 1, skip this — you already have it.

### 3. Discover consumers with `LSP findReferences`

For each key symbol — especially event constants, exported functions, interfaces — use `findReferences` to discover all consumers.

CodeGraph and CocoIndex results include file paths and line numbers. Use these directly:

```
codegraph_context returned:
  UPLOAD_EVENT — filePath: "src/events/constants.ts", line: 5

→ LSP findReferences(filePath: "src/events/constants.ts", line: 5, character: 14)
← returns ALL files that reference UPLOAD_EVENT
```

For `character`, use the column where the symbol name starts (e.g., `export const UPLOAD_EVENT` → character 14).

`findReferences` returns the complete reference list from the language server — no further verification needed.

### 4. Precise types with `LSP hover`

When `codegraph_node` signatures don't fully resolve generics, unions, or inferred types, use `LSP hover` at the symbol position for the exact type.

### 5. Stop when your questions are answered

After each tool call: can you now answer what your task requires? If yes, stop. If no, identify the specific gap and fill it with the matching tool (see the table above).

## `Read` for code files

**Do NOT use `Read` on code files (`.ts`, `.tsx`, `.js`, `.jsx`, `.py`, `.go`, `.rs`, `.java`, `.swift`).** Use `codegraph_node(includeCode: true)` to see a symbol's implementation, or `LSP` for references and types.

The only exception: you need to see **cross-function control flow within a single file** — how multiple functions in the same file interact with each other. Use a line range to limit context.

## File discovery

Use `codegraph_files` to explore project structure (directories, file lists, language breakdown). Use `Glob` for files not in the CodeGraph index. Limit Glob to max 3 calls, directory-scoped.

## Non-code files

`.md`, `.json`, `.yaml`, `.css`, `.svg` — use Glob/Grep/Read freely. The CodeGraph + CocoIndex + LSP workflow applies only to code files.
