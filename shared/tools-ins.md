# Boot (first invocation per session)

Load the tool schemas you may need (mechanical, no judgment):

    ToolSearch query="select:LSP" max_results=5

Skip if already loaded earlier in the session. grep/rg/find run via Bash and Read needs no loading.

# Before each tool call (MUST)

Above EVERY tool invocation — including each call inside a parallel batch — write one line in this exact shape:

    To get {want}, call {full tool invocation with every argument}

**This line IS your tool call.** The invocation that follows must use the same arguments verbatim. There is no separation between "what you declare" and "what you pass" — writing the call out is how you construct it.

Examples:

    To seed file:line for the resume upload flow,
    call Bash: rg -n "uploadResume" src/server

    To read UploadService.uploadResume at the line rg found,
    call Read(file_path="src/server/upload.service.ts", offset=118, limit=60)

    To find every caller of loginUser from its definition,
    call LSP.findReferences(operation="findReferences", filePath="src/auth.ts", line=42, character=10)

Before writing the line, match `{want}` against the scenarios below and pick the **bottommost** one that fits.


# Tool selection

Read bottom-up — pick the **bottommost** scenario whose "have" matches. Top = last resort, bottom = preferred.

Two hard rules:
- Search with a PRECISE grep/rg — scope to a path, anchor the pattern, pass `-n`, so the result set ≈ 1; pipe to `head` if it could be large.
- Never read a whole source file — locate the range first, then Read only that range (offset/limit).

<have: a file path glob | want: matching file paths>
  Bash: rg --files src | rg '\.ts$'        # or: find src -name '*.ts'

<have: an exact string or regex | want: every matching line as file:line>
  Bash: rg -n "TODO\(.*\)" src

<have: a symbol name only | want: where it is defined / its callers>     → two-step
  Bash: rg -n "loginUser" src              # seed file:line:col
  then run the LSP scenario below at that location

<have: file:line:col of a definition | want: all callers / references>     ← precise, no noise
  LSP.findReferences(operation="findReferences", filePath="src/auth.ts", line=42, character=10)

<have: a file path + a located line range | want: that code>     ★ TOP — the canonical read move
  Read(file_path="src/auth.ts", offset=<start line>, limit=<~40-80>)   # tight window; widen only if the body overflows

If you genuinely need a whole short / non-source file (config, JSON), Read it directly — the range IS the file.
