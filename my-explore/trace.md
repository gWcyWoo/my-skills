# Trace

The query asks how data or control flows across files. The entry point is identifiable.

## Steps

1. **Find the entry point.** — `probe search_code` when only a concept is known; `LSP workspaceSymbol` when a name is known.

2. **Open the entry with `lsp: true`.** — `probe extract_code files=["<file>#<symbol>"] lsp=true`. This returns body, callees, and callers in one response. **Use this only at the entry hop.**

3. **Identify the next hops** from the call hierarchy returned in step 2. Skip built-in and framework calls.

4. **Trace the next hops with plain `extract_code`.** — batch them in one call: `probe extract_code files=["api/x.ts#fn","store/y.ts#setter"]`. Reopen `lsp: true` only at a later hop where both directions are required again.

5. **Find callers.** — `LSP findReferences symbol="<name>" in="<file>"`. Never `Grep` for callers.

6. **Summarize** the full chain in the `Call edges` slot as `caller → callee` with `file:line`.

## Cost Rule

`lsp: true` payloads run 10–15k tokens each. Use it at most two or three times per Trace task. Plain `extract_code` is the default for all other hops.

**Stop condition:** the full flow is captured from entry to terminal. Typical cost: 3–5 tool calls.
