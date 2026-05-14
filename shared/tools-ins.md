# Boot (first invocation per session)

Run these three calls to load deferred tool schemas (mechanical, no judgment):

    ToolSearch query="select:mcp__probe__extract_code,mcp__probe__search_code" max_results=5
    ToolSearch query="select:mcp__ast-grep__find_code,mcp__ast-grep__find_code_by_rule" max_results=5
    ToolSearch query="select:LSP" max_results=5

Skip if already loaded earlier in the session.

# Before each tool call (MUST)

Above EVERY tool invocation — including each call inside a parallel batch — write one line in this exact shape:

    To get {want}, call {full tool invocation with every argument including #anchors}

**This line IS your tool call.** The invocation that follows must use the same arguments verbatim. There is no separation between "what you declare" and "what you pass" — writing the call out is how you construct it. If your line includes `#symbol` anchors, your invocation includes them. If your line omits them, you are committing to a whole-file extract and must justify it.

Examples:

    To get the body of UploadService.uploadResume,
    call probe.extract_code(files=["src/server/upload.service.ts#UploadService.uploadResume"])

    To get the bodies of actionUploadResume and RecruitmentService.createRecruitmentAndDefaultTasks,
    call probe.extract_code(files=[
        "src/actions/upload-resume.ts#actionUploadResume",
        "src/server/recruitment.service.ts#RecruitmentService.createRecruitmentAndDefaultTasks",
    ])

    To seed file:line for the resume upload flow,
    call probe.search_code(query="resume upload flow", path=".")

Before writing the line, match `{want}` against the scenarios below and pick the **bottommost** one that fits. If that scenario has a GATE, the GATE must hold at the moment you write the line — if not, pick a different scenario.


# Tool selection

Read bottom-up — pick the **bottommost** scenario whose "have" matches. Top = last resort, bottom = preferred.

<GATE: unlocks ONLY if no prior search_code call exists in this session — otherwise SKIP this scenario>
<have: a single concept phrase (no AND, no OR, no `|`, no `\b`, no regex), no file, no symbol | want: seed a file:line to start>
  probe.search_code(query="user login flow", path=".")
  # Query is a short natural-language phrase. NOT boolean. NOT regex. If you need AND/OR, use Grep.

<have: a file path glob | want: matching file paths>
  Glob(pattern="src/**/*.ts")

<have: an exact string or regex | want: every matching line>
  Grep(pattern="TODO\\(.*\\)", path="src")

<have: a structural code pattern | want: matching code shapes>
  ast_grep.find_code(pattern="class $X extends Component")
  # e.g. "all classes extending Y", "all calls to fn($_, null)"

<have: a symbol name only | want: all callers / references>     → ok (two-step)
  probe.search_code(query="loginUser definition", path=".")   # seed file:line:col
  LSP.findReferences(filePath="src/auth.ts", line=42, character=10)

<have: file:line:col of a definition | want: all callers / references>     ← good (precise, 1pt, no noise)
  LSP.findReferences(operation="findReferences", filePath="src/auth.ts", line=42, character=10)

<have: a file path + one symbol name | want: that symbol's body/definition>     ← prefer
  probe.extract_code(files=["src/auth.ts#loginUser"])

<have: ANY symbol names visible in prior tool results (Class.method, Class, function names, even single-symbol cases) + their file paths | want: their bodies in one call>     ★ TOP — the canonical exploration move; matches whenever symbols are known
  probe.extract_code(files=["src/auth.ts#loginUser", "src/auth.ts#logout", "src/user.ts#User"])
  probe.extract_code(files=["src/api/route.ts#POST", "src/handler.ts#processOrder", "src/db.ts#OrderRepo"])
  probe.extract_code(files=["src/server/upload.service.ts#UploadService.uploadResume", "src/server/recruitment.service.ts#RecruitmentService.createRecruitmentAndDefaultTasks", "src/server/recruitment.service.ts#RecruitmentService.activateNextTask"])

For wiring / constants files where there is no meaningful symbol to anchor (e.g. a top-level `eventBus.on(...)` block, a file of `export const FOO = ...`), do not use `extract_code` — the file's structure is already visible in the prior `search_code` results. If you genuinely need to read the file in full, fall back to `Read`.
