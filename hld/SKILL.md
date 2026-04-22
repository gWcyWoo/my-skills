---
name: hld
description: Invoked by the `u-0` skill after requirements analysis is complete. Produces design contracts for integration tests and code implementation.
---

# High-Level Design (HLD)

Produces a design contract that `testcase integration` and `c-0` consume directly. Interfaces become API contracts, module boundaries become mock boundaries, interaction flows become integration test cases.

## Inputs

1. **Procedure directory path** — the directory containing `understand.md`
2. **Code context from analysis phase** — code navigation results (via `Skill(my-explore-0)`) are already available from the preceding analysis. Use them directly for design work (e.g., extracting reused module interfaces).

Read `{procedure_dir}/u-0.md` to get the requirements analysis (Task Type, Analysis, Affected Files, Acceptance Criteria).

## Scope Constraint

**All design decisions must be scoped strictly to the requirements analysis in `understand.md`** (Task Type, Analysis, Affected Files, Acceptance Criteria). Do not introduce goals, scope, or functionality not present in the requirements analysis. Code context from the analysis phase is available for tooling (e.g., extracting interfaces via LSP), but does not expand design scope.

If gaps are discovered during design, document them in Design Decisions with the limitation noted. Do not expand scope within HLD.

## Process

### Step 0: Load Architecture Rules (MANDATORY)

Before any design work, load the project's architecture and convention rules. These rules are **binding constraints** on all design decisions in Step 2. A design that violates a loaded rule is invalid.

**0a. Load shared rules:** Determine project type by checking `package.json` dependencies and file extensions of the Affected Files from `understand.md`. Read the applicable files:

| Condition | File to Read |
|---|---|
| Any frontend (`.vue`/`.tsx`/`.jsx` files) | `~/.code/shared-rules/frontend/architecture.md` |
| Any backend (non-frontend `.ts`/`.js` files) | `~/.code/shared-rules/backend/ddd.md` |

**0b. Load project design constraints:** Read the project's CLAUDE.md **in the repository root** using the `Read` tool. This is the project-specific CLAUDE.md, not the global `~/.claude/CLAUDE.md`. If no project CLAUDE.md exists in the repository root, output "Step 0b N/A" and proceed.

Extract every rule that constrains **code structure, data flow, API patterns, response types, URL conventions, or file organization**. Ignore workflow/process rules (e.g., "Phase 1: Requirements Understanding"). List the extracted rules explicitly — they become **binding design constraints** for Step 2.

**Constraint enforcement in Step 2:**
- Every interface, signature, and module boundary in Step 2 MUST comply with the loaded rules.
- If a design choice conflicts with a loaded rule, the rule wins. Document the conflict and the rule-compliant alternative in Design Decisions.

### Step 1: AC-Driven Design Scope

**Principle**: ACs define WHAT to design. Code defines HOW to design it. Code context does not expand scope — it informs implementation decisions within AC boundaries.

**Process**:
1. List every AC from `understand.md`
2. For each AC, identify what design elements are needed (interface? flow? module?) by examining the relevant code
3. Do NOT add design elements that don't serve an AC

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

**REUSED MODULE RULE:** When the design references reusing an existing component/module, you MUST use code navigation (via `Skill(my-explore-0)`) to extract its complete public interface (all required props/params, their types). Do NOT rely on visual code scanning. Paste the extracted interface into the HLD and design against it. Incomplete interface extraction = broken contract.

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
- **Async state mutation order**: When a Flow involves an async operation (API call, fetch, promise) AND a state change (e.g., opening a modal, updating a flag), the Expected Output MUST specify the causal order between the async operation and the state change. Example: "calls sharePost API; on success sets isShareOpen = true; on failure isShareOpen remains false" — NOT "opens share modal and calls API". Both testcase and code derive behavior from this ordering; ambiguity causes implementation/test mismatch.

### Step 3: Author-Side Quick Check (before writing output)

Before writing hld.md, run these quick checks. This is a FAST author-side sanity check — the thorough independent review happens later via a separate reviewer agent.

1. **Constraint compliance** — scan HLD against loaded architecture rules. If any obvious violation, fix before writing.
2. **Reused module interfaces** — if reusing a component, verify via code navigation (via `Skill(my-explore-0)`) that HLD defines all required props.
3. **Affected files sync** — every file in HLD should be in understand.md Affected Files and vice versa.
4. **Flow completeness** — every Success flow should have an Error/N/A counterpart.
5. **AC coverage** — every AC should have at least one Flow (structural ACs exempt).
6. **No implementation in contracts** — signatures and flow outputs should be declarative, not procedural.

If any issue found → fix the HLD before writing. Do NOT produce formal review tables — the independent reviewer agent handles that.

**Do NOT write review output to any file.** The reviewer agent will produce the formal `audit/review.md` with content-verified tables.

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
- **`c-0`**: Interfaces + Signatures → implementation contracts. Module Boundaries → file/module structure. Interaction Flow → orchestration logic.
