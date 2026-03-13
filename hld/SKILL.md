---
name: hld
description: Invoked by the `understand` skill after requirements analysis is complete. Produces design contracts for integration tests and code implementation.
---

# High-Level Design (HLD)

Produces a design contract that `testcase integration` and `code` consume directly. Interfaces become API contracts, module boundaries become mock boundaries, interaction flows become integration test cases.

## Input Constraint

**The sole input to HLD is the requirements analysis from `understand` Step 2.** All design work must be scoped strictly to that analysis (Task Type, Analysis, Affected Files, Acceptance Criteria). Do not introduce goals, scope, or functionality not present in the requirements analysis.

If gaps are discovered during design, return to the `understand` phase to amend — do not expand scope within HLD.

## Process

### Step 0: Load Architecture Rules (MANDATORY)

Before any design work, load the project's architecture and convention rules. These rules are **binding constraints** on all design decisions in Step 2. A design that violates a loaded rule is invalid.

Determine project type by checking `package.json` dependencies and file extensions of the Affected Files from `understand` output. For each matching condition, check whether the file's content is already present in the current conversation context (loaded by a prior skill). Read ONLY the files whose content is NOT already in context.

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

**Constraint enforcement in Step 2:**
- Every interface, signature, and module boundary in Step 2 MUST comply with the loaded rules.
- If a design choice conflicts with a loaded rule, the rule wins. Document the conflict and the rule-compliant alternative in Design Decisions.
- Example: if `reactjs.md` requires "2+ hooks on same state → extract custom hook", the Module Boundaries table MUST reflect that extraction. Designing a single component that manages 2+ state operations inline is a rule violation.

### Step 1: Identify Design Scope

Based on the `understand` Step 2 output (Affected Files and Acceptance Criteria):
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

**REUSED MODULE RULE:** When the design references reusing an existing component/module, you MUST use LSP (`hover` or `documentSymbol`) to extract its complete public interface (all required props/params, their types). Do NOT rely on visual code scanning. Paste the extracted interface into the HLD and design against it. Incomplete interface extraction = broken contract.

#### Module Boundaries

```
| Module | Responsibility | Internal Dependencies | External Boundary |
|--------|---------------|-----------------------|-------------------|
| OrderForm | collects user input, calls submit | useOrderService | none |
| useOrderService | orchestrates order creation | OrderValidator | fetch (network) |
| OrderValidator | validates order rules | none | none |
```

- **Internal Dependencies**: other modules in this system — integration tests render these for real, no mocking.
- **External Boundary**: anything outside this module's control — network / DB / third-party API / **props and callbacks passed from parent components**. This is what `testcase integration` mocks (N ≤ 1 rule). Parent-provided inputs (e.g., `onClose`, `upload: UseSequentialUploadReturn`) are external boundaries, not internal dependencies — the module does not own or control them.

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
- **AC ID**: Every flow MUST trace to an AC ID from `understand`. No orphan flows.
- **Output Category**: Classify each flow's expected output by its observable nature. This column is a **design-time classification** — downstream test types use it to determine testability.
  - `State Change` — the interaction produces an observable state mutation or return value (hook state update, store change, computed value change, function return value).
  - `Side Effect` — the interaction only forwards to an external boundary with no state change in the module (e.g., triggers DOM click, forwards callback invocation, calls `stopPropagation`). Only the delegation itself is observable.
  - `Mixed` — both state mutation and external delegation occur.
- **Path Type**: Success / Error / Boundary / N/A — one of four. Use `N/A` only for explicit "no failure possible" documentation rows.
- **Flow ID format**: `F{n}` sequential.
- **Flow granularity**: Each distinct user interaction within an AC gets its own Flow row(s). If an AC covers multiple interactions (e.g., drag, click, delete), each interaction needs at least one Flow. Do NOT collapse multiple interactions into a single Flow row.
- **Error path coverage**: Every interaction that has a success Flow MUST also have an error/boundary Flow if failure is possible (e.g., hash computation fails, network error, validation fails). If no failure is possible for a specific interaction, add a row in the Flow table with Path Type = `N/A` and Expected Output explaining why (e.g., "pure state reset, no external call — no failure path").

### Step 3: Return Output

Return the complete HLD Design Output to the `understand` skill. Do NOT present to user, do NOT ask for confirmation, do NOT stop. The `understand` skill handles self-check, optional Codex audit, presentation, and user confirmation.

The returned output MUST include all of the following sections:
- Interfaces (type/interface definitions)
- Function Signatures (with return type structures)
- Module Boundaries (table)
- Module Interaction Flow (table)
- Design Decisions (key decisions with rationale)

After the `understand` flow completes and the user confirms, this HLD serves as direct input for:
- **`testcase integration`**: Module Boundaries → mock boundary identification. Interaction Flow rows → integration test cases. AC ID → traceability.
- **`code`**: Interfaces + Signatures → implementation contracts. Module Boundaries → file/module structure. Interaction Flow → orchestration logic.
