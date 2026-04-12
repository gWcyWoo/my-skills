# tool.md

## How to choose

Choose the first scenario whose preconditions are already satisfied and whose tool closes the current `Missing` with the fewest calls and the narrowest scope.

When multiple scenarios fit, prefer the route with:

1. a stronger existing anchor (`file`, `symbol`, `line`, `literal`, `ID`, exact path)
2. more structured and bounded output
3. a smaller search radius
4. lower side effects

Do not use a broader scenario once a narrower anchored scenario is already available.

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

- `mcp__language_server__get_project_symbols`
- `mcp__probe__search_code`
- `mcp__ast_grep__find_code`
- `rg -n`
  when the target symbol is already known.

**Notes**

- Use `file:line` only when the local node itself is the target.
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

## Scenario: file known, symbol name unknown

**Intent**  
The file is known, but you still need the declaration names in that file to choose the right target.

**Preconditions**

- exact file is known
- the symbol name is genuinely unknown
- getting the file’s declaration list directly closes the current `Missing`

**Use**

- `mcp__ast_grep__find_code pattern="<single parseable declaration shape>"` when the declaration shape is known
- `rg -n "<exact text>" <file>` only when testing a narrow literal or declaration anchor inside that same file

**Avoid**

- repo-wide search
- `mcp__language_server__get_symbols`
- using broad symbol-listing just to “see what is in the file”

---

## Scenario: symbol name known, file unknown

**Intent**  
Find where a known symbol is declared across the project.

**Preconditions**

- stable symbol name is known
- file is unknown

**Preferred**

- `mcp__language_server__get_project_symbols query="<name>"`

**Fallback if LSP is unavailable**

- `mcp__probe__search_code query="<exact symbol or exact literal>" path="<scoped dir>"`

**Avoid**

- `mcp__language_server__get_symbols`
- broad symbol listing on guessed files
- broad concept search when the exact symbol name is already known

**Notes**

- If the symbol name is very generic, narrow the path first if possible.

---

## Scenario: every caller / reference of a symbol

**Intent**  
Every code location that references one exact symbol.

**Preconditions**

- symbol identity is known precisely enough for semantic references

**Preferred**

- `mcp__language_server__get_symbol_references`

**Fallback if LSP is unavailable**

- use scoped structural or scoped text search only when the call shape is stable enough, and note that aliases, renamed imports, namespace access, or destructuring may be missed

**Avoid**

- repo-wide `rg -n` as the first choice for semantic references

---

## Scenario: outgoing calls made from inside one symbol

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
Test a narrow literal or declaration hypothesis locally.

**Preconditions**

- exact text is known
- the file or nearest relevant directory is already known

**Use**

- `rg -n "<exact text>" <known-file-or-nearest-dir>`

**Allowed on source only when**

- it is a first scoped anchor inside a known file or nearest directory, or
- it directly tests a narrow literal / declaration hypothesis before switching back to a structured tool

**Avoid**

- regex alternation on source
- repo-wide literal search when a local path is already known
- using `rg -n` to browse code broadly

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

## Scenario: only a concept is known

**Intent**  
Bootstrap from domain keywords when no usable anchor exists yet.

**Preconditions**

- no stable file, symbol, line, literal, or exact path anchor exists yet

**Use**

- `mcp__probe__search_code query="<domain keywords>" path="<scoped dir>"`

**Limits**

- bootstrap only
- at most two attempts per query
- stop immediately once a concrete file, symbol, literal, or path anchor surfaces

**Avoid**

- repeated concept searches after anchors already exist

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

- `README`
- spec
- config
- JSON/YAML/TOML
- logs

---

## Recovery rules

- If a tool errored or returned less than expected, fix the arguments and retry the same tool once before switching.
- If LSP reports unavailable, mark it unavailable for the rest of the query and use non-LSP routes.
- If a source `file:line` extraction returns only an import, comment, or trivial node, switch to the enclosing symbol route instead of broadening search.
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
