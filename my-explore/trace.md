# Trace

The query asks how data or control flows across files. The goal is to build one anchored chain, not to broadly search related code.

## Steps

1. **Resolve the entry anchor.**
   The first goal is not "find related code", but to obtain one concrete entry anchor:
   - `file#symbol`, or
   - `file:line`
   If only a concept is known, use one bootstrap search to get the first anchor. Do not continue until the anchor is concrete.

2. **Open the entry anchor.**
   - If the exact `file#symbol` is known and both callers and callees are needed, use `probe extract_code files=["<file>#<symbol>"] lsp=true` at the entry hop only.
   - Otherwise use plain `probe extract_code`.
   Record the current anchor before proceeding.

3. **Advance one hop at a time.**
   For each hop, identify exactly one justified next anchor from the current anchor.
   Allowed question: "From this anchor, what is the next relevant symbol or storage boundary in the flow?"
   Disallowed question: "What else in the repo mentions this concept?"

4. **Keep the chain anchored.**
   Every subsequent step must be expressed as:
   - current anchor
   - next anchor
   - why this is the next hop
   Once an anchor exists, do not return to broad `probe search_code` unless the chain is broken and you explicitly say so.

5. **Use narrow fallback when LSP is unavailable.**
   If language server is unavailable:
   - stay in the current file or nearest relevant directory
   - use AST shape search (`ast-grep find_code`) to get the next anchor
   - do not widen to repo-wide concept search while the current chain is still localizable

6. **Trace callers only when the query needs reverse flow.**
   Use `LSP findReferences`. Never `Grep` for callers on source files.
   Do not branch into caller tracing unless the question actually asks for reverse flow.

7. **Summarize as an anchor chain.**
   Report `Call edges` as:
   `anchor A → anchor B → anchor C`
   Each edge must be justified by code opened from the prior anchor.

## Drift Rules

A Trace run is drifting if any of these happen:
- two consecutive steps fail to produce a new anchor
- broad search resumes after a concrete anchor already exists
- multiple unrelated branches are pursued in parallel
- a new subsystem is opened without proving its connection to the current anchor

If drift occurs, stop and restate the current anchor, the missing link, and the next single hypothesis.

## Cost Rule

Use `lsp: true` only at the entry hop or at a later hop where both directions are required again. Plain `extract_code` is the default.

**Stop condition:** the full flow is captured as one anchored chain from entry to terminal. Typical cost: 3–5 tool calls.
