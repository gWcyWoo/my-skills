# Discovery — no specific symbol known

## Steps

1. **Search by domain concept** — **Probe search_code** scoped to the likely directory.
2. **Scan structure** (when you have files but not specific symbols yet) — use **ast-grep find_code** with patterns like `interface $NAME { $$$ }`, `type $NAME = $$$`, `export function $NAME` to list what a file or directory contains. Use **ast-grep analyze-imports** with `mode: "discovery"` to see module dependencies. Then **extract_code** the symbols you need.
3. **Narrow down** — once you have a concrete file or function, switch to Pinpoint or Trace.
4. If Probe is unavailable, fall back to Grep with keyword patterns.
