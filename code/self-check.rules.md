# Code Review Rules

Review the implementation code against HLD contracts, the author's Implementation Checklist, and general code quality standards. Invoke the `my-explore` skill first to load code navigation methodology, then use its tools to obtain evidence — do NOT use `Read` on source code files.

## Inputs

- `understand.md` — Acceptance Criteria, Affected Files
- `hld.md` — Interfaces, Function Signatures, Module Boundaries, Module Interaction Flow
- `{procedure_dir}/audit/code-checklist.md` — the author's Implementation Checklist (Step 1c) and traceability tables (Step 2c/2d), extracted from the code agent's output by the main session before invoking self-check
- Source code files (accessed via `my-explore` tools only — do NOT use `Read`)

## Part 1: HLD Contract Fidelity (P0 — Blocker)

These checks verify the code implements the HLD contracts exactly. Any mismatch is a blocker.

**Table 1 — Signature Match (one row per function signature defined in hld.md):**

Obtain the actual signature from the source code. Compare against the HLD-defined signature.

| HLD Signature (quote from hld.md) | Actual Signature (quote from tool output) | Match? | Status |
|------------------------------------|-------------------------------------------|--------|--------|
| "handleTopicSelect: (tag: string) => void" | "(tag: string) => void" | yes | ✅ |
| "useTopic returns { duplicateTag: string \| null, ... }" | "missing duplicateTag in return" | no — field not implemented | ❌ |

**Table 2 — Interface Match (one row per interface/type defined in hld.md):**

Obtain the actual type definition from source code. Compare fields and types against HLD.

| HLD Interface (quote from hld.md) | Actual Type (quote from tool output) | Match? | Status |
|------------------------------------|---------------------------------------|--------|--------|
| "TopicItem { tag: string; count: number }" | "{ tag: string; count: number }" | yes | ✅ |

**Table 3 — Flow Edge Verification (one row per Caller → Callee edge in hld.md Flow table):**

Verify the connecting value (import path, function argument, URL) is correct in the actual code.

| HLD Edge | Connecting Value | Expected (from hld.md) | Actual (from tool output) | Match? | Status |
|----------|-----------------|------------------------|---------------------------|--------|--------|
| PostContainer → useTopic.handleTopicSelect | function call arg | "tag string" | "handleTopicSelect(topic.tag)" — string arg | yes | ✅ |

**Table 4 — Forward Traceability (one row per HLD element):**

Every HLD element (interface, signature, flow step) must have a corresponding implementation. Verify existence in the source code.

| HLD Element | Expected Location (from Affected Files) | Found? (quote from tool output) | Status |
|-------------|----------------------------------------|---------------------------------|--------|
| "handleTopicSelect" | hooks.ts | yes — line 45 | ✅ |
| "duplicateTag state" | hooks.ts | no — not found | ❌ |

**Table 5 — Reverse Traceability (one row per new/modified export in source code):**

Every new or modified export in the Affected Files must trace back to an HLD element. List exports from source code, then check each against HLD.

| File | Export (from tool output) | HLD Element | Status |
|------|--------------------------|-------------|--------|
| hooks.ts | handleTopicSelect | HLD Signature: "handleTopicSelect" | ✅ |
| hooks.ts | formatTopicDisplay | (no HLD element) | ❌ scope creep |

**Completeness check (mandatory):**

```
Verification: hld.md defines N function signatures and M interface types. Tables 1+2 have N+M rows. Match: YES/NO.
```

## Part 2: Security (P0 — Blocker)

Scan all Affected Files for dangerous patterns. Every pattern must have a row — even if clean.

**Table 6 — Security Pattern Scan (one row per pattern):**

| Pattern | Files Scanned | Found? (quote if found) | Status |
|---------|---------------|------------------------|--------|
| XSS: innerHTML / dangerouslySetInnerHTML | all Affected Files | no matches | ✅ |
| Injection: eval / Function() | all Affected Files | no matches | ✅ |
| Hardcoded secrets: password= / secret= / api_key= | all Affected Files | no matches | ✅ |
| Unescaped user input in URL construction | all Affected Files | (quote if found) | ✅/❌ |

## Part 3: Author Checklist Verification (P1 — Major)

The code author produced an Implementation Checklist (Step 1c) and self-verified it (Step 2d). This part independently verifies both.

**Table 7 — Checklist Completeness (one row per applicable architecture rule from loaded rules files):**

Load the same architecture rules that the code author loaded in Step 1. For each rule, check: is it relevant to the current task's Affected Files? If relevant, is it in the author's checklist? A relevant rule missing from the checklist means the author's filter was too aggressive.

| Rule (quote from rules file) | Relevant to this task? | In Author's Checklist? | Status |
|------------------------------|----------------------|----------------------|--------|
| "NO any: Explicitly define types" | yes — TS files modified | yes — checklist item #3 | ✅ |
| "Use useCallback to wrap event handlers" | yes — hooks modified | no — missing from checklist | ❌ gap |
| "Lazy-load large modules on feature activation" | no — no new modules | N/A | EXEMPT |

**Table 8 — Checklist Execution (one row per item in the author's Implementation Checklist):**

For each item the author claimed was satisfied (✅), independently verify using tools.

| # | Checklist Item (quote from author) | Author's Evidence | Independent Verification (quote from tool output) | Status |
|---|-----------------------------------|-------------------|--------------------------------------------------|--------|
| 1 | "NO any — all types explicit" | "hooks.ts: all typed" | scanned Affected Files for `as any` / `: any` — 0 matches, confirmed | ✅ |
| 3 | "useCallback for handlers" | "hooks.ts:L45 wrapped" | inspected handleTopicSelect — function not wrapped in useCallback | ❌ author's self-check was wrong |

**Completeness check (mandatory):**

```
Verification: Author's Implementation Checklist has N items. This table has N rows. Match: YES/NO.
```

## Part 4: Code Quality (P1/P2)

Obtain function bodies from source code, then evaluate quality.

**Table 9 — Function Complexity (one row per function in Affected Files with > 10 lines):**

Get the function body. Check line count, nesting depth, and branch count.

| Function | File | Lines | Max Nesting | Branches | Status |
|----------|------|-------|-------------|----------|--------|
| handleTopicSelect | hooks.ts | 12 | 2 | 3 (if/else/return) | ✅ |
| processFormData | hooks.ts | 45 | 4 | 8 | ❌ too complex — split |
| PostContainer | container.tsx | 30 | 1 | 2 | ✅ |

Thresholds:
- **Lines**: > 30 lines per function → P2 suggestion to split
- **Max Nesting**: > 3 levels → P1 must refactor
- **Branches**: > 5 per function → P1 must refactor

**Table 10 — Naming Quality (one row per new/modified symbol in Affected Files):**

List all symbols in Affected Files. Check naming conventions against loaded rules (camelCase for functions, PascalCase for components/interfaces, etc.).

| Symbol | Kind | Name Convention Expected | Actual | Status |
|--------|------|------------------------|--------|--------|
| handleTopicSelect | function | camelCase | camelCase | ✅ |
| TopicItem | interface | PascalCase | PascalCase | ✅ |
| temp | variable | camelCase + descriptive | "temp" — not descriptive | ❌ P2 |

**Table 11 — Error Handling (one row per async operation or external call in Affected Files):**

Check if async operations have error handling.

| Function | Async Operation (quote from code) | Error Handling Present? | Status |
|----------|----------------------------------|------------------------|--------|
| handleTopicSelect | (no async) | N/A | EXEMPT |
| fetchTopics | `await fetch(url)` | yes — wrapped in try/catch | ✅ |
| loadData | `await api.get(path)` | no — no try/catch or .catch() | ❌ P1 |

**Table 12 — Type Safety (one row per type concern found by scanning Affected Files):**

Scan for type safety violations in Affected Files.

| Check | Found? (quote if found) | Status |
|-------|------------------------|--------|
| `as any` / `: any` usage | no matches | ✅ |
| `as` type assertions (non-any) | "as TopicItem" at hooks.ts:L32 — verify if necessary | ⚠️ verify |
| `!` non-null assertions | no matches | ✅ |
| Unchecked access on nullable value | (verify with type inspection) | ✅/❌ |

## Part 5: Verification Confirmation (P0 — Blocker)

Run the actual verification commands to confirm the author's claim that all tests pass and lint is clean.

**Table 13 — Verification Gate (run each command):**

| Command | Expected | Actual Result | Status |
|---------|----------|---------------|--------|
| `npx vitest run 2>/dev/null` | 0 failures | [paste result summary] | ✅/❌ |
| `npx playwright test 2>/dev/null` | 0 failures (or skip if no e2e files) | [paste result summary] | ✅/❌ |
| `lint 2>/dev/null` | 0 errors | [paste result summary] | ✅/❌ |

All three must pass. Any failure is a P0 blocker.

## Summary

```
| Category | Severity | Total | Pass | Fail | Exempt |
|----------|----------|-------|------|------|--------|
| Signature Match | P0 | X | X | X | X |
| Interface Match | P0 | X | X | X | X |
| Flow Edge Verification | P0 | X | X | X | X |
| Forward Traceability | P0 | X | X | X | X |
| Reverse Traceability | P0 | X | X | X | X |
| Security Pattern Scan | P0 | X | X | X | X |
| Checklist Completeness | P1 | X | X | X | X |
| Checklist Execution | P1 | X | X | X | X |
| Function Complexity | P1/P2 | X | X | X | X |
| Naming Quality | P2 | X | X | X | X |
| Error Handling | P1 | X | X | X | X |
| Type Safety | P1 | X | X | X | X |
| Verification Gate | P0 | X | X | X | X |

Verdict: ALL PASS / X P0 blockers, X P1 issues, X P2 suggestions
```
