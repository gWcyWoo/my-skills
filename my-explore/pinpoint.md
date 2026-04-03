# Pinpoint — component/function name or UI label known

1. Grep the known text, scoped to the likely directory → get file:line.
2. Probe extract_code or Read (offset+limit, 30-50 lines) to see the code.
3. If the code delegates to another function/file → LSP goToDefinition at that call site.
4. NEVER use Grep to find the definition file — LSP does it in 1 call.
