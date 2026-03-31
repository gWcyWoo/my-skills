# Understand + HLD Review Rules

Review requirement.md, understand.md, and hld.md by filling these tables. Every cell must quote actual text from the files. ID-only references are forbidden.

## Part 1: Requirement Traceability

Read `requirement.md` and `understand.md`.

**Table 1 — AC Purity + Traceability (one row per AC):**

| AC | AC Text (quote from understand.md) | Source (quote from requirement.md) | Purity | Traceability | Status |
|----|------------------------------------|------------------------------------|--------|-------------|--------|
| AC-01 | "When the user clicks share..." | R1: "Click the share icon to open the share panel" | PASS | PASS | ✅ |
| AC-08 | "When API fails, empty list shown" | (no matching sentence in requirement.md) | PASS | FAIL — overclaim | ❌ |

- **Purity**: AC must NOT contain file paths, function names, or technology choices. Structural ACs (refactoring) are exempt — mark "N/A (structural)".
- **Traceability**: AC must trace to a specific sentence in requirement.md (R-number) or Existing Behavior Inventory (BI-number). Quote the source text.

**Completeness check (mandatory):** After filling the table, append this verification line:

```
Verification: understand.md contains N ACs (AC-01 through AC-XX). This table has N rows. Match: YES/NO.
```

If NO — find the missing ACs and add rows. Do NOT proceed to Table 2 until the counts match.

**Table 2 — Gap Detection (mechanical):**

1. Collect all R/BI numbers from Table 1's Source column
2. List the complete set of requirement sentences (R1, R2, ...) and BI items (BI-1, BI-2, ...)
3. Gap = any number NOT in collected set

```
Collected: R1, R2, R3, BI-1, BI-2, BI-3, BI-4, BI-5
Complete:  R1, R2, R3, R4, BI-1, BI-2, BI-3, BI-4, BI-5, BI-6
Gap:       R4, BI-6 ← no AC covers these
```

**Completeness check (mandatory):** After filling the gap analysis, append this verification line:

```
Verification: understand.md defines X R-numbers (R1 through R?) and Y BI-numbers (BI-01 through BI-??). Complete set above lists X+Y items. Match: YES/NO.
```

If NO — re-read understand.md and correct the complete set before reporting gaps.

## Part 2: Design Coverage (skip if no hld.md)

Read `hld.md` and `understand.md`.

**Table 3 — AC → Flow (one row per AC, quote Flow content):**

Every AC must map to at least one Flow. Structural ACs (no user interaction, e.g. refactoring or module extraction) are EXEMPT from Flow mapping — mark "EXEMPT".

| AC | AC Text (quote from understand.md) | Flow | Flow Expected Output (quote from hld.md) | Status |
|----|-----------------|------|------------------------------------------|--------|
| AC-01 | "When user clicks share..." | F1 | "success response, panel visible" | ✅ |
| AC-05 | "When error occurs..." | — | (no Flow in hld.md covers AC-05) | ❌ gap |
| AC-10 | "Extract share logic into standalone module" | — | (structural, no interaction) | EXEMPT |

**Table 4 — Flow → AC (one row per Flow, quote AC content):**

Every Flow must trace back to at least one AC. A Flow without a corresponding AC is an orphan — it implements behavior that was never requested.

| Flow | Flow Expected Output (quote from hld.md) | AC | AC Text (quote from understand.md) | Status |
|------|-----------------------------|----|-------------------------------------|--------|
| F1 | "success response, panel visible" | AC-01 | "When user clicks share..." | ✅ |
| F8 | "error state displayed" | — | (no AC in understand.md covers this behavior) | ❌ orphan |

**Table 5 — Error Path Coverage (one row per success Flow):**

A success Flow is one whose expected output describes a normal/happy outcome. For each success Flow, there must be a corresponding error Flow that handles the failure case of the same operation. Identify success vs error by the Flow's expected output content (e.g., "returns SUCCESS..." vs "returns error...").

| Success Flow | Success Output (quote from hld.md) | Error Flow | Error Output (quote from hld.md) | Status |
|-------------|----------------------|-----------|--------------------------------|--------|
| F1 | "returns SUCCESS with resultId" | F4 | "returns error with joined messages" | ✅ |
| F9 | "record created, event emitted" | — | (no error Flow exists in hld.md) | ❌ missing |

## Part 3: Design Correctness (skip if no hld.md)

Read `hld.md`. These tables check internal consistency within the HLD itself.

**Table 6 — Signature Consistency (one row per cross-module call in Flow table):**

For each Flow that involves a caller → callee interaction, verify the caller's arguments match the callee's parameter types as defined in the Signatures section. This catches type mismatches across module boundaries.

| Flow | Caller | Callee | Caller Args (quote from hld.md) | Callee Params (quote from hld.md) | Match? | Status |
|------|--------|--------|--------------------------------|----------------------------------|--------|--------|
| F1 | OrderForm | useOrderService | "order: OrderData" | "function createOrder(order: OrderData)" | yes | ✅ |
| F3 | OrderForm | useOrderService | "id: number" | "function createOrder(order: OrderData)" | no — number vs OrderData | ❌ |

**Table 7 — Data Origin Traceability (one row per field in Flow Expected Output):**

Every named data value (field, ID, status code, count, etc.) that appears in a Flow's Expected Output must be traceable to an upstream source: a preceding Flow's output, a function parameter, or an external input. Behavioral descriptions (e.g., "panel visible", "toast shown") are not data values and are excluded from this check. A data value without a traceable origin indicates a design gap — data appears from nowhere.

| Flow | Output Field (quote from hld.md) | Origin (quote upstream source from hld.md) | Status |
|------|--------------------------------|-------------------------------------------|--------|
| F1 | "resultId" | External Input: "orderId from form submission" | ✅ |
| F3 | "totalCount" | (no upstream Flow or input produces totalCount) | ❌ missing origin |

**Table 8 — Flow Continuity (one row per Flow):**

Each Flow's expected output must be a direct consequence of its trigger. If reaching the output requires intermediate steps (e.g., validation, authorization, gateway calls), those steps must appear as separate Flows in the design.

| Flow | Caller → Callee (quote from hld.md) | Input (quote from hld.md) | Expected Output (quote from hld.md) | Skipped State? | Status |
|------|-------------------------------------|--------------------------|-------------------------------------|---------------|--------|
| F1 | "OrderForm → useOrderService" | "valid order data" | "order saved, confirmation shown" | no | ✅ |
| F5 | "CheckoutPage → PaymentService" | "payment request" | "payment recorded in DB" | yes — skips payment gateway call | ❌ |

**Table 9 — Async State Mutation Order (one row per Flow with async operation + state change):**

For each Flow whose Expected Output involves BOTH an async operation (API call, fetch, network request) AND a state mutation (flag toggle, modal open/close, list update), verify that the Expected Output specifies the causal order: which happens first, and what happens on success vs failure. Ambiguous ordering (e.g., "opens modal and calls API") causes testcase and code to derive conflicting behavior.

| Flow | Async Operation (quote from hld.md) | State Change (quote from hld.md) | Order Specified? | Success/Failure Paths Clear? | Status |
|------|-------------------------------------|----------------------------------|-----------------|------------------------------|--------|
| F3 | "calls sharePost API" | "sets isShareOpen = true" | yes — "on success sets isShareOpen" | yes — "on failure isShareOpen remains false" | ✅ |
| F7 | "submits form and updates list" | (no explicit order) | no — ambiguous | no | ❌ |

Skip Flows that have no async operation or no state change (pure sync state updates, pure side effects).

**Table 10 — Boundary Correctness (one row per dependency in Module Boundaries table):**

Each dependency in the Module Boundaries table must be correctly classified. Internal = other modules in this system (rendered for real in tests). External = anything outside the module's control (network, DB, third-party APIs, parent-provided props/callbacks — mocked in tests).

| Module | Dependency | Classification (quote from hld.md) | Correct? | Status |
|--------|-----------|-----------------------------------|----------|--------|
| OrderForm | useOrderService | Internal: "useOrderService" | yes — same system module | ✅ |
| OrderForm | fetch | Internal: "fetch" | no — fetch is network, should be External | ❌ |

## Part 4: Design Compliance (skip if no hld.md)

Read `hld.md` and the project's architecture rules. These tables check whether the HLD design follows loaded rules.

**Before filling these tables**, load ONLY architecture rules (not language/framework implementation rules):

| Condition | File to Read |
|---|---|
| Any frontend (`.vue`/`.tsx`/`.jsx` files) | `/Users/Woo/.code/shared-rules/frontend/architecture.md` |
| Any backend (non-frontend `.ts`/`.js` files) | `/Users/Woo/.code/shared-rules/backend/ddd.md` |

Also read the project's CLAUDE.md in the repository root for project-specific constraints.

Do NOT load language-specific rules (typescript.md, reactjs.md, vue3.md, etc.) — those are implementation rules checked during the code phase, not design rules.

Every applicable rule must have at least one row — regardless of pass or fail. Quote the rule text and the HLD element being checked. A rule with no row means it was skipped, which is forbidden.

**Table 11 — Architecture Compliance (one row per architecture rule):**

Check module decomposition, dependency direction, layer boundaries, and structural patterns against loaded architecture rules.

| Rule Source | Rule (quote from rules file) | HLD Element | HLD Text (quote from hld.md) | Status |
|-------------|----------------------------|-------------|------------------------------|--------|
| frontend/architecture.md | "UI components must not import data layer directly" | OrderForm | "dependencies: [useOrderService]" (service layer, not data) | ✅ |
| frontend/architecture.md | "Max 3 internal dependencies per module" | CheckoutPage | "dependencies: [OrderForm, PaymentForm, ShippingForm, CouponWidget]" (4 deps) | ❌ |

**Table 12 — Interface & Abstraction Compliance (one row per rule):**

Check interface design, abstraction level, and contract patterns. This includes both built-in abstraction rules and project-specific interface rules.

Built-in rules (always check — one row per category, scan ALL signatures and Flow outputs):
- No control flow language: `if`, `else`, `switch`, `?:` (ternary), "checks whether"
- No iteration language: `for`, `while`, `map`, `forEach`, "loops over", "iterates"
- No error handling language: `try`, `catch`, `throw`, "catches", "retries"
- No direct manipulation: "assigns X = Y", "sets flag to", "falls back to"
- No markup/template syntax: framework-specific rendering directives
- No imperative verbs: "renders", "mutates", "dispatches"

| Rule Source | Rule (quote or built-in pattern) | HLD Element | HLD Text (quote from hld.md) | Status |
|-------------|--------------------------------|-------------|------------------------------|--------|
| built-in | No iteration language | Sig: HotTopics | "renders tag list using map" — "map" is iteration | ❌ |
| built-in | No error handling language | F6 Output | "catches error and returns []" — "catches" | ❌ |
| built-in | No control flow language | (all signatures and outputs scanned) | (no control flow language found) | ✅ |
| typescript.md | "All public functions must have explicit return types" | doSearch | "function doSearch(): SearchReturn" | ✅ |

**Table 13 — Flow Compliance (one row per flow/interaction rule):**

Check Flow design patterns, error handling conventions, and interaction patterns against loaded architecture rules.

| Rule Source | Rule (quote from rules file) | HLD Element | HLD Text (quote from hld.md) | Status |
|-------------|----------------------------|-------------|------------------------------|--------|
| frontend/architecture.md | "Error flows must surface user-visible feedback" | F4 | "returns error with joined messages, toast shown" | ✅ |
| backend/ddd.md | "Service layer must not skip domain validation" | F2 | "useOrderService calls OrderValidator before save" | ✅ |

## Summary

```
| Category | Total | Pass | Fail | Exempt |
|----------|-------|------|------|--------|
| AC Purity + Traceability | X | X | X | X |
| Gap Detection | X gaps found | | | |
| AC → Flow | X | X | X | X |
| Flow → AC | X | X | X | X |
| Error Path Coverage | X | X | X | X |
| Signature Consistency | X | X | X | X |
| Data Origin Traceability | X | X | X | X |
| Flow Continuity | X | X | X | X |
| Async State Mutation Order | X | X | X | X |
| Boundary Correctness | X | X | X | X |
| Architecture Compliance | X | X | X | X |
| Interface & Abstraction Compliance | X | X | X | X |
| Flow Compliance | X | X | X | X |

Verdict: ALL PASS / X issues found
```
