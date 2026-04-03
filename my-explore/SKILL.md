---
name: my-explore
description: Code navigation methodology. Invoke before any code exploration to load tool schemas and navigation rules.
---

# Code Navigation

You MUST execute these ToolSearch calls before any exploration. Do NOT skip:

1. ToolSearch("ast-grep")
2. ToolSearch("probe")
3. ToolSearch("LSP")

If a ToolSearch returns no results, that tool is unavailable — skip it.

## Tool superiority — MUST use over Grep/Read when applicable

Grep is ONLY for the initial text lookup to get file:line. Once you have a position, NEVER use Grep again. Use these instead:

| After you have file:line, use | NOT | Why | Returns → use for |
|------|-----|-----|------|
| **LSP goToDefinition** | Grep to find definition file | 1 call → exact target | file:line of definition → extract_code there |
| **LSP outgoingCalls** | Read body + Grep each callee | 1 call → complete call list | file:line of each callee → extract_code directly, NO Grep |
| **LSP incomingCalls** | Grep function name across project | 1 call → all callers | file:line of each caller → extract_code directly |
| **LSP findReferences** | Grep symbol name | 1 call → all references | file:line of each ref → extract_code to see usage context |
| **ast-grep find_code** | Grep with regex | 1 call → AST-precise | file:line of each match → extract_code or Read |
| **Probe extract_code** | Read with guessed offset/limit | 1 call → complete block | full function/class body → understand logic |
| **Probe search_code** | Grep when name is unknown | Semantic search | file:line candidates → extract_code to verify |

All LSP operations require `filePath` + `line` + `character` (1-based). Get these from Grep first.

**NEVER use LSP documentSymbol** — it dumps all symbols in a file (often 100+), wastes tokens. If Grep returns 0 results, widen the Grep pattern (e.g. `handle.*Class`) or use Probe search_code.

## Classify, then load execution steps

Classify the question, then Read the corresponding file from this skill's directory:

| Type | Signal | File to Read |
|------|--------|-------------|
| **Pinpoint** | Component/function name or UI label known | `pinpoint.md` |
| **Trace** | How data/control flows across files | `trace.md` |
| **Discovery** | No specific symbol known, only abstract concepts | `discovery.md` |
| **Structural** | Find all code matching an AST pattern | `structural.md` |

**Default to Pinpoint.** Read the file, then follow its steps exactly.

After each tool call: answer found? → stop.
