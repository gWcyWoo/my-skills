---
name: my-explore-0
description: Use when Kimi needs lightweight code exploration in an unfamiliar or non-trivial codebase. Tells Kimi how to analyze a need and what is forbidden; tool choice is Kimi's own judgment within these constraints.
---

<MANTRA>
每次行动前默念：
"一次一调，阶段锁死，六调用封顶，提取后不复搜。"
</MANTRA>

<GOAL>
Turn the user prompt into the minimum decisive context for the next step.
</GOAL>

<STATE_MACHINE>
探索必须严格按以下三阶段推进，绝不跳过、绝不回退。

阶段 1 — LOCATE（定位）：只允许以下工具
  ├─ `mcp__probe__search_code`        — 概念搜索，首回合唯一入口
  ├─ `mcp__language_server__get_symbol_definitions` — 裸名查定义（仅当已知 1 个精确符号且文件未知）
  └─ `mcp__ast_grep__find_code`       — 结构模式匹配（仅当需要匹配 AST 形状时）
  ★ 此阶段恰好使用 1 次工具调用后即结束，绝不重复。

阶段 2 — EXTRACT（提取）：只允许以下工具
  ├─ `mcp__probe__extract_code`       — 读取代码片段（按 #Symbol 或 :line-range）
  └─ `wc -l <path>`（Shell）           — 仅用于确认文件总行数（≥2 个文件时批量传参）
  ★ 此阶段可以多次调用，但每次只能是 1 个工具调用。

阶段 3 — VERIFY（验证）：只允许以下工具
  ├─ `mcp__language_server__get_symbol_definitions`  — 验证符号存在性
  ├─ `mcp__language_server__get_symbol_references`   — 查找调用方
  └─ `mcp__language_server__get_diagnostics`         — 类型/编译错误
  ★ 此阶段每次只能 1 个工具调用，且仅当确实需要验证时才进入。

STOP（停止）：满足 <TERMINATION_CHECKLIST> 中全部条件后输出结论。

⚠️ 阶段锁死规则：
- 进入阶段 2 后，永远不再使用 search_code / ast_grep.find_code / grep / rg / Grep / Shell find 等任何搜索/匹配工具。
- 进入阶段 3 后，永远不再使用 extract_code。
- 任何阶段调用该阶段白名单之外的工具 = 违规，必须立即停止并报告。
</STATE_MACHINE>

<SINGLE_CALL_LOCK>
- 每个回合（turn）只能发出恰好 1 个工具调用。
- 并行调用、批量调用、一次发多个工具 = 绝对禁止。
- 必须等待工具返回结果后，分析结果，再决定下一个调用。
- 本规则优先级高于一切效率考量。
</SINGLE_CALL_LOCK>

<TOOLS>
按阶段白名单使用，禁止清单外工具：

- `mcp__probe__search_code` — 阶段 1 专用。语义/关键词搜索。
- `mcp__probe__extract_code` — 阶段 2 专用。提取代码片段。
- `mcp__ast_grep__find_code` — 阶段 1 专用。结构模式匹配。
- `mcp__language_server__get_symbol_definitions` — 阶段 1 或 3。
- `mcp__language_server__get_symbol_references` — 阶段 3。
- `mcp__language_server__get_diagnostics` — 阶段 3。
- `Shell` 仅用于 `wc -l` — 阶段 2 专用，且 ≥2 文件时必须批量传参。

明确禁止用于源码探索的工具（无论任何阶段）：
`ReadFile`、`Grep`（native grep/rg）、`Glob`、`Shell`（除 wc -l 外）、
`SearchWeb`、`FetchURL`。
</TOOLS>

<TOOL_USAGE_TEMPLATES>
阶段 1 — LOCATE 的调用模板：

probe.search_code — 概念发现（不知道具体符号时）
```
{
  "path": "<repo root>",
  "query": "resume parse pipeline",
  "lsp": true
}
```
- Natural-language phrase, 2–5 words. No `exact:true`. No `AND`/`OR` across short common words. No quoted literals.
- 此调用在一个探索周期中只能出现 1 次。

language_server.get_symbol_definitions — 裸名定位（恰好 1 个符号，文件未知）
```
{ "symbolName": "findLLMSetting" }
```
- Terminal identifier only. Never `Class.method`, never dotted access.
- 一个探索周期中最多 1 次（阶段 1 或 3，不同时使用）。

ast_grep.find_code — 结构匹配
```
{
  "pattern": "fetch($URL, { method: 'POST' })",
  "path": "<repo root>",
  "lang": "typescript"
}
```
- Pattern must include real structure around `$VAR` metavariables. Never bare `$FUNC(...)` or bare `$X`.
- 仅阶段 1 可用，且一个周期最多 1 次。

阶段 2 — EXTRACT 的调用模板：

probe.extract_code — 按符号提取
```
{
  "path": "<repo root>",
  "files": ["src/server/infrastructure/llm/factory.ts#LLMFactory"],
  "format": "markdown",
  "lsp": true,
  "allowTests": false
}
```
- `files[]` entries must be `realFilePath#SymbolName` or `realFilePath:line`. Never directory#Symbol, never `:1`, never URL-encoded paths.

probe.extract_code — 按行范围提取
```
{
  "path": "<repo root>",
  "files": ["src/server/application/task/task-executor.factory.ts:33-45"],
  "format": "markdown",
  "lsp": true
}
```

阶段 3 — VERIFY 的调用模板：

language_server.get_symbol_references — 查找调用方
```
{ "symbolName": "createExecutor" }
```
- Same rule: terminal identifier. If coordinates required, pass from prior definition call.

language_server.get_diagnostics — 文件级错误
```
{ "filePath": "src/server/infrastructure/llm/factory.ts" }
```
</TOOL_USAGE_TEMPLATES>

<OUTPUT_FORMAT>
每次工具调用前，你的可见回复必须包含（按顺序）：

1. **工具调用许可证**（必须出现，一行）：
   ```
   [PHASE: LOCATE|EXTRACT|VERIFY] → [TOOL: 工具名] → [TARGET: 目标描述] → [RULE: 规则依据]
   ```
   例如：
   ```
   [PHASE: LOCATE] → [TOOL: search_code] → [TARGET: "workshop chat reward"] → [RULE: STATE_MACHINE 阶段 1]
   ```

2. **用户需求的单句重述**

3. **缺失信号**（最多 3 个）。如果用户已给出全部信息，写 "none — answering directly"。

4. **文件中心假设计划**（file-centric hypothesis plan）：
   ```
   Hypothesis plan:
     - src/server/.../factory.ts → expected: LLMFactory class + 4 create* methods
     - src/server/.../chat.interface.ts → expected: ChatInterface shape
   ```
   - 计划单位是 FILE，不是 symbol。
   - 已知全部路径 → 阶段 2 直接用 extract_code(files=[...]) 批量覆盖。
   - 只知符号名 → 阶段 1 用 get_symbol_definitions 定位文件，再加入计划。
   - 不知任何路径 → 阶段 1 用一次 search_code 发现文件，再进入阶段 2。

只有完成以上 4 步后，才能发出工具调用。

---

**工具调用之间的回复**（收到结果后、发出下一次调用前）：

必须且只能是 ONE 行，EXACT 格式：

```
→ <result>. <shortname1>[<tag>] <shortname2>[<tag>] ... next: <tool | done>
```

Tags：
- `[COMPLETE L1-Ln]` — 返回内容覆盖 L1..Ltotal
- `[OPEN L<a>-?]` — 部分内容；Ltotal 未知
- `[missing-in-complete]` — 符号在 COMPLETE 文件中缺失 → 结论性不存在
- `[unknown-file]` — 符号需要但文件尚未定位

非文件调用用：
```
→ <result>. candidates=[f1,f2,...] | symbol-not-found | sizes={f1:n1,f2:n2}. next: <tool | done>
```

规则：
- `[OPEN]` 且未知 Ltotal → 下一次必须是 `wc -l`（阶段 2）。
- `[missing-in-complete]` → 黑名单生效；不再验证。
- 所有计划项解决（每个为 `[COMPLETE]`、`[missing-in-complete]` 或已满足）→ 进入 STOP，输出最终结论。

⚠️ 多行或冗长的叙述本身就是规则违规。
</OUTPUT_FORMAT>

<TERMINATION_CHECKLIST>
输出最终结论前，必须逐项勾选。缺少任一勾选 = 继续探索，不许输出结论：

□ `search_code` 最多用了 1 次（或 0 次，如果文件路径已知）
□ `ast_grep.find_code` 最多用了 1 次（或 0 次）
□ `get_symbol_definitions` 最多用了 1 次（阶段 1 或 3，不重复）
□ 没有使用 `ReadFile` / `Grep`（native grep/rg） / `Glob` / `Shell`（除 wc -l 外）读源码
□ 每个回合只发出了 1 个工具调用，从未并行
□ 阶段 1 结束后未再使用任何搜索/匹配工具
□ 所有结论有 `extract_code` 的文本证据支撑
□ 输出中包含正确的 `[COMPLETE]` / `[missing-in-complete]` / `[unknown-file]` 标签
</TERMINATION_CHECKLIST>

<SELF_ENFORCEMENT>
如果我在任何时候意识到我可能违反了 STATE_MACHINE、SINGLE_CALL_LOCK、TERMINATION_CHECKLIST 或 OUTPUT_FORMAT 中的任何规则，我必须：
1. 立即停止当前操作
2. 向用户声明："我注意到操作 [X] 可能违反 [规则名]，已暂停。请指示。"
3. 等待用户指示，绝不继续
</SELF_ENFORCEMENT>

<BUDGET>
Maximum 6 tool calls per exploration.
Calls beyond 3 are allowed only when you can name the specific unresolved gap that still blocks a correct answer.
If you cannot name that gap, stop.
</BUDGET>

<EVIDENCE_CHECKLIST>
Pick the one that matches the user's intent. These are the minimum evidence to stop; do not keep exploring past them.
- Locate behavior: one candidate owner + one exact extract.
- Explain a method: exact method extract + direct references only if callers matter.
- Trace impact: definition + references + nearest affected boundary.
- Scope a refactor: canonical abstraction + structurally similar sites + validation surface.
- Match a code shape: one structural-match query + one representative extract confirming a real match.
- Diagnose a type or compile error: diagnostics first, then definition of the offending symbol.
</EVIDENCE_CHECKLIST>

<STOP_RULE>
Stop when the owner, execution path, impact surface, and validation path are clear enough to answer correctly. If the next output will ask the user to pick between design options, each option must first be anchored in real code evidence — not guesses.
</STOP_RULE>

<FORBIDDEN>
以下禁令优先级低于 STATE_MACHINE 和 SINGLE_CALL_LOCK。如果状态机已阻止该行为，无需重复检查。

- Never read an entire code file at once.
- Never run `mcp__probe__extract_code` with `:1`. Use the exact matched line from search results, or prefer `#SymbolName`.
- Never pass a directory path or repo root to `mcp__probe__extract_code` with a `#SymbolName` suffix.
- Never pass a URL-encoded file path (`%28`, `%29`, `%20`, etc.) to any tool. Decode first.
- Never pass `exact:true` to `mcp__probe__search_code`.
- Never combine multiple short common words with `AND` in `mcp__probe__search_code`.
- Never retry `mcp__probe__search_code` with broader queries after zero results for exact symbol.
- Never fall back to search after `mcp__probe__extract_code` with `#SymbolName` returns zero.
- Never broaden the search space once an exact target is already known.
- Never pass a dotted call expression (`Foo.bar`) as symbol name to language_server tools.
- Never run `mcp__ast_grep__find_code` with bare `$FUNC(...)` or bare `$X`.
- Never use `get_symbol_definitions` to read a full method/class body — pivot to `extract_code`.
- Never re-read `SKILL.md` during an exploration turn.
- When any `language-server.*` tool returns infra-level error once, treat ENTIRE family as UNAVAILABLE for this turn. Pivot per rules above.
- Never treat a batched `extract_code` result as N independent lookups. If symbol absent from `[COMPLETE]` file, conclude missing — no verification.
- **Named blacklist** — after a file is marked `[COMPLETE]`, NEVER call any tool to "verify" a missing symbol in that same file. This includes: get_symbols, get_server_projects, get_server_status, start_server, another extract_code on same file, search_code scoped to that file, ast_grep scoped to that file, get_diagnostics on that file.
- Never express hypothesis plan as flat list of symbol names. Plan units are FILES.
</FORBIDDEN>
