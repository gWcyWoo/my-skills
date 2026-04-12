# tool.md

## Purpose

This file routes code-exploration tool choice.

Use it together with the skill's internal decision loop.

The goal is not a globally shortest path.
The goal is the **best next step under current evidence**.

Move only downward on the anchor ladder for the same `Missing`:

`concept` -> `path/file` -> `file:line` -> `file#symbol` -> `semantic reference`

Once a stronger anchor is available, do not move back to a weaker route unless that anchor was proven wrong.
Once `file#symbol`, a known handler, or a known owner file exists for the current `Missing`, weaker routes may be used only to test one unresolved exact literal hypothesis inside that anchored scope. They must not be used to broadly scan adjacent fields, sibling concepts, or likely-related names.

## How to choose

Choose the first scenario whose preconditions are already satisfied and whose tool can directly close the current `Missing`.

When multiple scenarios fit, prefer the route with:

1. a stronger current anchor
2. more structured and bounded output
3. a smaller search radius
4. lower side effects
5. fewer follow-up branches

A route is invalid if a narrower anchored route is already available.

---

## Global ban on `search_code` misuse

`mcp__probe__search_code` is bootstrap-only.

It is forbidden when the proposed query contains any of:

- regex alternation such as `|`
- two or more symbol-like identifiers
- declaration-shape text such as `export`, `class`, `const`, `type`, `interface`, `async`, `function`, `=>`
- exact filenames, file extensions, or known paths
- a list of constant names, event names, method names, or symbol names

If any of the above are present, this is not concept search.
Choose an anchored route instead.

---

## Scenario: exact body of a known symbol

**Intent**  
The body of one specific function, method, class member, callback, or exported symbol.

**Preconditions**

- `file` is known
- `symbol` is known well enough to name the target

**Use**

- `mcp__probe__extract_code files=["<file>#<symbol>"]`

**Prefer batching when**

- one `Missing` needs several tightly coupled symbol bodies together

**Avoid**

- `mcp__probe__search_code`
- `mcp__ast_grep__find_code`
- `rg -n`
- repo-wide search
  when the target symbol is already known.

**Notes**

- Use `file:line` only when the local AST node itself is the target.
- If the real target is the enclosing block, identify the symbol first and then use `file#symbol`.

---

## Scenario: batched exact reads

**Intent**  
The bodies of several related symbols returned in one response.

**Preconditions**

- each target is already known as `file#symbol` or as a precise local `file:line` node

**Use**

- `mcp__probe__extract_code files=["a#x","b#y","c#z"]`

**Prefer when**

- the current `Missing` depends on several tightly related bodies together
- batching removes obvious extra calls

---

## Scenario: local AST node at a known line

**Intent**  
A precise local node at a known `file:line`, not the enclosing function.

**Preconditions**

- `file` is known
- exact line is known
- the local node itself is the target

**Use**

- `mcp__probe__extract_code files=["<file>:<line>"]`

**Avoid**

- using `file:line` when what you really need is the containing function, method, or callback

---

## Scenario: registration callback body

**Intent**  
The needed behavior lives in an anonymous callback passed to a registration API, such as `eventBus.on(...)`, `on(...)`, `addEventListener(...)`, route registration, queue consumers, or similar callback-based hooks.

**Preconditions**

- `file` is known
- the registration call, route-binding call, or event literal is known
- the needed fact is the callback behavior, not the registration shell itself

**Use**

- `mcp__ast_grep__find_code pattern="<registration call with callback placeholder>"`
- then switch to the enclosing behavioral unit when identifiable
- prefer `file#symbol` when the callback is named or belongs to a named enclosing owner

**Avoid**

- `mcp__probe__extract_code files=["<file>:<line>"]` on the registration line when the answer depends on callback behavior
- treating the registration shell itself as the behavioral unit

**Notes**

- The registration line is often only a shell such as `eventBus.on(` or `router.post(`.
- If the callback is anonymous, treat it as an enclosing behavioral unit rather than a trivial local node.
- If the enclosing owner becomes identifiable, prefer `file#symbol` over further local-node extraction.

---

## Scenario: every caller / semantic reference of a known symbol

**Intent**  
Every code location that references one exact symbol.

**Preconditions**

- symbol identity is known precisely enough for semantic references
- LSP is usable

**Use**

- `mcp__language_server__get_symbol_references`

**Avoid**

- repo-wide `rg -n` as the first choice for semantic references

---

## Scenario: outgoing calls or value transitions inside one known symbol

**Intent**  
The callees or value transitions inside one known symbol body.

**Preconditions**

- exact `file#symbol` is known

**Use**

- `mcp__probe__extract_code files=["<file>#<symbol>"]`

**Notes**

- Read call expressions and transitions from the returned body.
- Do not switch to a broader tool if the body already contains the needed evidence.

---

## Scenario: entry-hop trace bundle

**Intent**  
At the first hop of a trace, get the symbol body together with callers and callees in one response.

**Preconditions**

- exact `file#symbol` is already known
- you need both callers and callees immediately
- separate `extract_code` + `get_symbol_references` would otherwise run back-to-back on the same symbol
- LSP is usable

**Use**

- `mcp__probe__extract_code files=["<file>#<symbol>"] lsp=true`

**Avoid**

- using this beyond the entry hop
- using this when exact `file#symbol` is not already known
- using this when callers or callees are not both needed right now

**Notes**

- This route is expensive. Open it only when it truly shortens the path.

---

## Scenario: exact literal inside a known file or nearest relevant directory

**Intent**  
Test one narrow literal or declaration hypothesis locally.

**Preconditions**

- exact text is known
- the file or nearest relevant directory is already known

**Use**

- `rg -n "<exact text>" <known-file-or-nearest-dir>`

This route is only for testing one unresolved exact literal hypothesis.
It must not be used to broadly inspect nearby concepts once a stronger anchor already exists.

**Allowed on source only when**

- it is a first scoped anchor inside a known file or nearest directory, or
- it directly tests one narrow literal / declaration hypothesis before switching back to a structured tool

**Avoid**

- regex alternation on source
- repo-wide literal search when a local path is already known
- using `rg -n` to browse code broadly
- packing multiple symbol names into one broad source search

---

## Scenario: code shape known, but not the symbol

**Intent**  
Find code by syntax shape rather than by exact text.

**Preconditions**

- you can express the target as a parseable single-node AST pattern

**Use**

- `mcp__ast_grep__find_code pattern="<single AST node pattern>"`

**If too many matches**

- `mcp__ast_grep__find_code_by_rule` with `inside`, `has`, or `follows`

**If the pattern fails to parse or match**

- `mcp__ast_grep__dump_syntax_tree`

**Avoid**

- text search when AST structure is the true constraint

---

## Scenario: exact symbol name known, file unknown

**Intent**  
Find where a known symbol is declared across the project.

**Preconditions**

- one stable symbol name is known
- file is unknown

**Preferred when LSP is usable**

- `mcp__language_server__get_project_symbols query="<name>"`

**Fallback when LSP is unavailable**

- `mcp__ast_grep__find_code pattern="<single declaration pattern containing the exact symbol>"`
- or `rg -n "\\b<exact symbol>\\b" <scoped dir>` when exact text is known and the scope can be kept tight

**Never**

- never fall back to `mcp__probe__search_code` when a stable symbol name is already known

**Avoid**

- broad concept search
- regex alternation over many symbol names
- broad symbol listing on guessed files

**Notes**

- If the symbol name is generic, narrow the directory first if possible.

---

## Scenario: file known, symbol name unknown

**Intent**  
The file is known, but the declaration name still is not.

**Preconditions**

- exact file is known
- the symbol name is genuinely unknown

**Preferred**

- `mcp__ast_grep__find_code pattern="<single parseable declaration shape>"` when the declaration shape is known
- `rg -n "<exact text>" <file>` only when testing a narrow literal or declaration anchor inside that same file

**Never**

- never use repo-wide search for this case
- never use `mcp__probe__search_code` for this case
- never use symbol listing just to browse

---

## Scenario: only a concept is known

**Intent**  
Bootstrap from domain keywords when no usable anchor exists yet.

**Preconditions**

- no stable `file`
- no stable `file:line`
- no stable `file#symbol`
- no exact path
- no exact symbol
- no exact literal tied to the code

**Use**

- `mcp__probe__search_code query="<domain keywords>" path="<scoped dir>"`

**Hard limits**

- exactly one call per reasoning chain
- the query must be conceptual, not structural
- the moment it returns a usable `file`, `file:line`, or `file#symbol` anchor, stop searching and switch immediately to an anchored route
- never use `mcp__probe__search_code` again in that same reasoning chain

**If it returns no usable anchor**

- do not retry `mcp__probe__search_code`
- answer with `[gap]`, or switch only if a new non-search anchor already exists

---

## Scenario: path question, not a content question

**Intent**  
The question is “which files match path X” rather than “which lines contain text Y”.

**Preconditions**

- the problem is about file paths, file names, or directory layout

**Use**

- `rg --files <root>`
- if needed, narrow with a second scoped `rg`

**Avoid**

- content search tools

---

## Scenario: non-source text search

**Intent**  
Search within non-source files.

**Preconditions**

- target file is non-source (`.md`, `.json`, `.yaml`, `.yml`, `.toml`, `.txt`, config, log)

**Use**

- `rg -n "<text>" <path>`

---

## Scenario: non-source file contents

**Intent**  
Read the raw contents of a non-source file.

**Preconditions**

- target file is non-source

**Use**

- direct file read

**Examples**

- README
- spec
- config
- JSON / YAML / TOML
- logs

---

## Recovery rules

- If a tool errored or returned less than expected, fix the arguments and retry the same tool once before switching.
- If LSP reports unavailable, mark it unavailable for the rest of the query and use non-LSP routes.
- If a source `file:line` extraction returns only an import, comment, directive, or trivial node, switch to the enclosing `file#symbol` route instead of broadening search.
- If an exact file path is already known, keep the search radius file-local until that path is shown to be wrong.
- If two successive calls fail to resolve the same `Missing`, stop varying tools on that hypothesis. Reframe the `Missing` or answer with `[gap]`.
- If the question is already answered at the current layer, stop. Do not drill into downstream callers, callees, or side effects unless the user explicitly asked.

## Priority under ambiguity

When multiple routes are valid, prefer the one that best satisfies the current `Missing` with:

1. fewer calls
2. stronger anchor
3. more structured output
4. narrower scope
5. lower side effects
6. less future branching
