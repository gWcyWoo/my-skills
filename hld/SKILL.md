---
name: hld
description: Invoked by the `understand` skill after requirements analysis is complete. Produces design contracts for integration tests and code implementation.
---

# High-Level Design (HLD)

Produces a design contract that `testcase integration` and `code` consume directly. Interfaces become API contracts, module boundaries become mock boundaries, interaction flows become integration test cases.

## Inputs

1. **Procedure directory path** — the directory containing `understand.md`
2. **Code context from analysis phase** — CodeGraph, LSP, and file contents are already available from the preceding analysis. Use them directly for design work (e.g., extracting reused module interfaces).

Read `{procedure_dir}/understand.md` to get the requirements analysis (Task Type, Analysis, Affected Files, Acceptance Criteria).

## Scope Constraint

**All design decisions must be scoped strictly to the requirements analysis in `understand.md`** (Task Type, Analysis, Affected Files, Acceptance Criteria). Do not introduce goals, scope, or functionality not present in the requirements analysis. Code context from the analysis phase is available for tooling (e.g., extracting interfaces via LSP), but does not expand design scope.

If gaps are discovered during design, document them in Design Decisions with the limitation noted. Do not expand scope within HLD.

## Process

### Step 0: Load Architecture Rules (MANDATORY)

Before any design work, load the project's architecture and convention rules. These rules are **binding constraints** on all design decisions in Step 2. A design that violates a loaded rule is invalid.

**0a. Load shared rules:** Determine project type by checking `package.json` dependencies and file extensions of the Affected Files from `understand.md`. Read the applicable files:

| Condition | File to Read |
|---|---|
| TypeScript (`.ts`/`.tsx` files) | `~/.claude/shared-rules/common/typescript.md` |
| Any frontend (`.vue`/`.tsx`/`.jsx` files) | `~/.claude/shared-rules/frontend/architecture.md` |
| Vue (`vue` in dependencies) | `~/.claude/shared-rules/frontend/vue3.md` |
| React (`react` in dependencies) | `~/.claude/shared-rules/frontend/reactjs.md` |
| Next.js (`next` in dependencies) | `~/.claude/shared-rules/frontend/nextjs.md` |
| Next.js fullstack (`next` + server actions) | `~/.claude/shared-rules/frontend/nextjs-fullstack.md` |
| Any backend (non-frontend `.ts`/`.js` files) | `~/.claude/shared-rules/backend/ddd.md` |
| Express (`express` in dependencies) | `~/.claude/shared-rules/backend/express.md` |
| MongoDB (`mongoose`/`mongodb` in dependencies) | `~/.claude/shared-rules/backend/mongodb.md` |

**0b. Load project design constraints:** Read the project's CLAUDE.md **in the repository root** using the `Read` tool. This is the project-specific CLAUDE.md, not the global `~/.claude/CLAUDE.md`. If no project CLAUDE.md exists in the repository root, output "Step 0b N/A" and proceed.

Extract every rule that constrains **code structure, data flow, API patterns, response types, URL conventions, or file organization**. Ignore workflow/process rules (e.g., "Phase 1: Requirements Understanding"). List the extracted rules explicitly — they become **binding design constraints** for Step 2.

**Constraint enforcement in Step 2:**
- Every interface, signature, and module boundary in Step 2 MUST comply with the loaded rules.
- If a design choice conflicts with a loaded rule, the rule wins. Document the conflict and the rule-compliant alternative in Design Decisions.

### Step 1: Identify Design Scope

Based on the `understand.md` output (Affected Files and Acceptance Criteria):
- Which existing modules are affected
- What new modules/components are needed
- What existing interfaces change

### Step 2: Design

#### Interface / Contract Definitions

Define data structures and contracts using the idioms of the project's language:

- TypeScript/JavaScript: `interface`, `type`
- Python: `Protocol`, `dataclass`, `TypedDict`
- Go: `interface`, `struct`
- Rust: `trait`, `struct`, `enum`
- Dart: `abstract class`, `mixin`, `class`
- Swift: `protocol`, `struct`, `enum`
- Objective-C: `@protocol`, `@interface`
- Other: use the language's native abstraction for contracts

#### Function / Method Signatures

Define signatures with input, output, and responsibility using the project's language conventions.

**HARD RULE: NO implementation details in HLD.** Define ONLY: type/interface declarations, function/method signatures (name, params, return type, one-line responsibility), module boundaries, and execution flow. Do NOT write function bodies, pseudo-code, algorithm steps, conditional logic, variable assignments, or any code that belongs inside a function. If you find yourself writing more than a signature, you are violating this rule. The implementer decides HOW; the HLD decides WHAT and WHERE.

**CONTRACT vs IMPLEMENTATION — the line:**
- **Contract** (MUST define in HLD): function parameters, return type **structure** (e.g., `Promise<ApiResponse<{ is_shared: boolean }>>`), props interfaces of reused components, error response shapes — anything the caller needs to know to call correctly.
- **Implementation** (MUST NOT define in HLD): function bodies, internal branching, how data is transformed, which utility is used internally.
- **Test**: if removing it would make the caller unable to determine how to call or what to expect back, it is a contract. Define it.

**REUSED MODULE RULE:** When the design references reusing an existing component/module, you MUST use LSP (`hover` or `documentSymbol`) to extract its complete public interface (all required props/params, their types). LSP tools are already loaded from the analysis phase. Do NOT rely on visual code scanning. Paste the extracted interface into the HLD and design against it. Incomplete interface extraction = broken contract.

#### Module Boundaries

```
| Module | Responsibility | Internal Dependencies | External Boundary |
|--------|---------------|-----------------------|-------------------|
| OrderForm | collects user input, calls submit | useOrderService | none |
| useOrderService | orchestrates order creation | OrderValidator | fetch (network) |
| OrderValidator | validates order rules | none | none |
```

- **Internal Dependencies**: other modules in this system — integration tests render these for real, no mocking.
- **External Boundary**: anything outside this module's control — network / DB / third-party API / **props and callbacks passed from parent components**. This is what `testcase integration` mocks (N ≤ 1 rule). Parent-provided inputs (e.g., `onClose`, `fetchData: () => Promise<Data>`) are external boundaries, not internal dependencies — the module does not own or control them.

#### Module Interaction Flow

Enumerate how modules collaborate. Each row = one interaction point = one potential integration test focus.

```
| Flow ID | AC ID | Caller | Callee | Input | Expected Output | Output Category | Path Type |
|---------|-------|--------|--------|-------|-----------------|-----------------|-----------|
| F1 | AC-01 | OrderForm | useOrderService | valid order data | success response, UI updates | State Change | Success |
| F2 | AC-01 | useOrderService | OrderValidator | order object | validation passes | State Change | Success |
| F3 | AC-02 | OrderForm | useOrderService | valid order data | API returns 500, error msg shown | State Change | Error |
| F4 | AC-03 | OrderForm | useOrderService | empty cart | validation fails, form shows error | State Change | Boundary |
```

Rules:
- **AC ID**: Every flow MUST trace to an AC ID from `understand.md`. No orphan flows.
- **Output Category**: Classify each flow's expected output by its observable nature. This column is a **design-time classification** — downstream test types use it to determine testability.
  - `State Change` — the interaction produces an observable state mutation or return value (hook state update, store change, computed value change, function return value).
  - `Side Effect` — the interaction only forwards to an external boundary with no state change in the module (e.g., triggers DOM click, forwards callback invocation, calls `stopPropagation`). Only the delegation itself is observable.
  - `Mixed` — both state mutation and external delegation occur.
- **Path Type**: Success / Error / Boundary / N/A — one of four. Use `N/A` only for explicit "no failure possible" documentation rows.
- **Flow ID format**: `F{n}` sequential.
- **Flow granularity**: Each distinct user interaction within an AC gets its own Flow row(s). If an AC covers multiple interactions (e.g., drag, click, delete), each interaction needs at least one Flow. Do NOT collapse multiple interactions into a single Flow row.
- **Error path coverage**: Every interaction that has a success Flow MUST also have an error/boundary Flow if failure is possible (e.g., hash computation fails, network error, validation fails). If no failure is possible for a specific interaction, add a row in the Flow table with Path Type = `N/A` and Expected Output explaining why (e.g., "pure state reset, no external call — no failure path").

### Step 3: Self-Check Gate (MANDATORY)

After completing the design, execute these checks before writing output. Each check MUST produce structured evidence in the exact format shown. "I checked and it looks fine" is NOT acceptable — output the structured comparison or it did not happen.

**Check 1: Project Design Constraint Compliance**
Verify the HLD against the project design constraints extracted in Step 0b. If Step 0b was N/A (no project CLAUDE.md), output "Check 1 N/A" and proceed to Check 2.

For each constraint extracted in Step 0b, output a structured comparison:
```
Constraint: "[exact quote from Step 0b extracted rules]"
HLD element: "[exact quote from your HLD output that this constraint applies to]"
Verdict: PASS / FAIL — [reason if FAIL]
```
If a constraint has no corresponding HLD element (the constraint's domain is not touched by this design), output: `Constraint: "..." → Not applicable to this HLD — SKIP`

If any FAIL: fix the HLD element before proceeding.

**Check 2: Module Boundary Completeness**

**Part A — Reused Module Interface Completeness**
For every component/module the HLD says to "reuse" or "integrate":
1. Use `LSP hover` on the component's export to extract its complete public interface (all props/params with types).
2. Output a field-by-field comparison:
```
Extracted interface (from LSP):
  - isOpen: boolean
  - onClose: () => void
  - fetchCallback: (id: string) => Promise<Partial<ShareInfo>>

HLD defines:
  - isOpen: boolean ✓
  - onClose: () => void ✓
  - fetchCallback: MISSING ✗
```
3. Any field marked ✗ = FAIL. Update HLD interfaces before proceeding.
4. If HLD does not reference any reused modules: output "Part A N/A".

**Part B — New Module Boundary Completeness**
For every new module in the HLD Module Boundaries table:
1. **Dependency check**: Cross-reference Function Signatures and Flow table — every dependency mentioned there (functions called, constants used, types imported) must appear in Internal Dependencies. Output:
```
Module: [module name]
  Signatures mention: [list of dependencies from Function Signatures]
  Flow table mentions: [list of dependencies from Flow table]
  Internal Dependencies declares: [what the table currently says]
  Missing: [any dependency not declared] ✗ ← FAIL
```
2. **External Boundary check**: External Boundary must be a real process/network boundary (HTTP call, file system, database), not an in-process dependency (shared library, framework context, imported utility). Output:
```
Module: [module name]
  External Boundary: "[what the table says]"
  Is this a process/network boundary? YES/NO — [reason] ✓/✗
```
3. **Signature completeness**: Every function in Function Signatures must have parameter types and return type specified. Output:
```
[function name]: parameter type? [type] ✓/✗ | return type? [type] ✓/✗
```
4. Any FAIL: update Module Boundaries before proceeding.
5. If HLD defines no new modules: output "Part B N/A".

**Check 3: Affected Files Sync**
1. List every file path that appears anywhere in the HLD output (Interfaces, Signatures, Module Boundaries, Flows).
2. List every file in the `understand.md` Affected Files section.
3. Output a two-column comparison:
```
HLD files                          | Affected Files list
-----------------------------------|-------------------
types.ts                           | ✓ listed
api/server/share.ts                | ✓ listed
constants.ts                       | ✗ NOT in Affected Files  ← FAIL
```
4. Any file in HLD but not in Affected Files = FAIL (add it to `understand.md`).
5. Any file in Affected Files but not referenced anywhere in HLD = FAIL (justify or remove it).

**Check 4: Flow Table Completeness**

Two parts, evaluated in a single pass over the Flow table:

**Part A — Interface-Flow Consistency**
1. List every field from each Interface defined in HLD §Interface/Contract Definitions.
2. For each field, search the Flow table's Input and Expected Output columns for a reference to that field.
3. Output a structured comparison:
```
Interface: UseFileSelectionReturn
  - files: FileWithHash[]        → F1 Expected Output ("files updated") ✓
  - isDragging: boolean          → F2 Expected Output ("isDragging = true") ✓
  - totalSize: number            → no Flow references totalSize ✗ ← FAIL
```
4. Any Interface field not referenced in any Flow = FAIL. Fix by either adding a Flow row or removing the field from the Interface.
5. If HLD defines no Interfaces: output "Part A N/A" and proceed to Part B.

**Part B — Error Path Coverage**
1. List every Flow with Path Type = `Success`.
2. For each, check whether a corresponding `Error`, `Boundary`, or `N/A` Flow row exists in the Flow table for the same interaction.
3. Output a structured comparison:
```
F1 (Success) → F6 (N/A: "sessionStorage.setItem cannot throw in this context") ✓
F2 (Success) → F5 (Error: "sessionStorage read fails, fallback to SSR data") ✓
F3 (Success) → no Error/Boundary/N/A row in Flow table ✗ ← FAIL
```
4. Missing row = FAIL. Fix by adding the missing Flow row to the HLD.

**Check 5: Bidirectional Traceability**

Every element must have an upstream source and a downstream consumer. No orphans in any direction.

**Part A — AC → Flow (no uncovered ACs)**
For each AC in understand.md, verify at least one Flow row references it. Structural ACs (verifiable by code inspection, not by module interaction) are exempt — annotate as "structural, no Flow needed."
```
AC-01 → F1, F2, F3 ✓
AC-02 → F4 ✓
AC-05 → no Flow references AC-05 ✗ ← FAIL (add Flow)
AC-10 (Structural) → structural AC, no module interaction → EXEMPT ✓
```

**Part B — Flow → AC (no orphan Flows)**
For each Flow row, verify its AC ID exists in understand.md:
```
F1 → AC-01 ✓
F8 → AC-08 — AC-08 does not exist in understand.md ✗ ← FAIL (remove Flow or it's SCOPE_CREEP)
```

**Part C — Signature → Flow (no orphan Signatures)**
For each function/method in Function Signatures, verify at least one Flow references it as Caller or Callee:
```
useSearch → F1 (Caller), F3 (Callee) ✓
formatDate → no Flow references it ✗ ← FAIL (remove signature or add Flow)
```

**Part D — Flow → Signature (no phantom calls)**
For each Caller/Callee in the Flow table, verify it exists in Function Signatures or Module Boundaries:
```
F4 Callee: handleSearchByKey → exists in useSearch signature ✓
F9 Callee: formatTimestamp → not in any signature ✗ ← FAIL (add signature)
```

Any FAIL: fix before proceeding.

**Check 6: Expression Boundary**

Each artifact must stay within its expressive scope. Violations indicate implementation logic leaking into design contracts.

Scan all Function Signatures and Flow Expected Output columns for these patterns:
- Conditional logic: `if`, `else`, `when`, `?:`, branching descriptions
- Code constructs: JSX tags (`<Component />`), variable assignments, loop keywords
- Implementation verbs: "catches", "retries", "falls back to", "checks whether"

```
Function Signatures:
  useSearch: "if key is empty, clears searchResult" ✗ ← FAIL (implementation logic — rewrite as: "input: empty key → output: searchResult becomes null")
  HotTopics: "renders tag list" ✗ ← FAIL (rendering is implementation — rewrite as: "input: HotTopicsProps → output: JSX.Element")

Flow Expected Output:
  F3: "searchResult remains null, HotTopics stays visible" ✓ (declarative state description)
  F6: "catches error and returns empty array" ✗ ← FAIL (rewrite as: "searchResult remains null")
```

Allowed in Function Signatures: type declarations, parameter names+types, return type, one-line responsibility summary (what, not how).
Allowed in Flow Expected Output: declarative state descriptions (what the state IS after the interaction, not how it got there).

Any FAIL: rewrite to declarative form before proceeding.

Only after all 6 checks pass with structured evidence, proceed to the output step.

Do NOT include self-check evidence in the output file — only the final HLD document.

### Step 4: Write Output

Write `{procedure_dir}/hld.md` with the complete HLD Design output. The file MUST include all of the following sections:

```markdown
## High-Level Design

### Interfaces
[Interface definitions]

### Function Signatures
[Signatures with descriptions]

### Module Boundaries
[Module boundary table]

### Module Interaction Flow
[Interaction flow table]

### Design Decisions
[Key decisions and rationale]
```

After writing `hld.md`, return to the caller (the analysis flow in `subagent-instructions.md`).

This HLD serves as direct input for:
- **`testcase integration`**: Module Boundaries → mock boundary identification. Interaction Flow rows → integration test cases. AC ID → traceability.
- **`code`**: Interfaces + Signatures → implementation contracts. Module Boundaries → file/module structure. Interaction Flow → orchestration logic.
