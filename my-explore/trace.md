# Trace — how data/control flows across files

1. Grep the entry point name, scoped to the likely directory → get file:line.
2. LSP prepareCallHierarchy(filePath, line, character) → get call hierarchy item.
3. LSP outgoingCalls → all called functions with their positions in 1 call. This eliminates N separate Grep searches.
4. For each callee: Probe extract_code at the position from outgoingCalls → see the body.
5. Repeat steps 2-4 for deeper hops if needed.
6. NEVER Grep callee names individually — outgoingCalls already gave you all positions.
7. Summarize the full flow once all hops are traced.
