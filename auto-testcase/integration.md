# Integration Test Rules (L7 Assembly-Locked Edition)

## 1. Scope

**Module Collaboration Verification**: An integration test is required when a function calls other modules. The boundary is:
- **Unit test**: one function, one behavior, no external module dependencies — tests pure logic in isolation.
- **Integration test**: a function calls other modules (e.g., `fetchServerApi` + `assertSuccess` + `buildUrl`) — mock only the outermost external boundary (network/DB), let all internal modules run for real. Drive different collaboration paths by providing different mock values.
- **E2E test**: real backend data + real UI — verifies that correct data is rendered correctly on screen.

**Key rule**: If a function calls other modules, its tests are integration tests, not unit tests. Mock the external boundary, then use different mock values to verify how the modules behave together under different conditions (success path, error path, edge cases).

**FORBIDDEN — Mock-as-Input-and-Output**: Mock values exist to drive internal module behavior, NOT to be asserted directly. If your test mocks a value and then asserts that the result equals that same mock value, you are testing the mock, not the modules. Ask: "What real internal behavior does this mock value trigger?" — assert that behavior's outcome. If no real internal behavior is triggered (e.g., the function is a pure passthrough with no transformation), there is no integration test to write.

---

## 2. Input Discovery

- **With HLD**: Use HLD-defined component interfaces and module boundaries as API contracts. The HLD is the sole contract. You may read type/interface definition files (e.g., `schema.ts`, `types.ts`) even if listed in Affected Files — they define contracts. You MUST NOT read files that contain function bodies or business logic (e.g., `parser.ts`, `api.ts`, `handler.ts`). See SKILL.md "Code Reading Boundaries" for the full rule.
- **Without HLD**: Use `codegraph_node(includeCode: true)` and `LSP hover` on symbols from `understand` → Affected Files. Extract component props, container interfaces, service method signatures. These become the API contracts. Do NOT invent APIs.

### 2b. HLD Edge Contract Extraction (mandatory when HLD exists)

From the HLD Module Interaction Flow, extract every **edge** (module A → module B) and identify its **contract** — the connecting value that crosses the boundary (URL path, function arguments, API endpoint, etc.):

```
| HLD Edge | Contract Type | Expected Value (derived from target module) |
|---|---|---|
| [moduleA → moduleB] | [URL / params / endpoint / ...] | [derived from target module's location or spec definition] |
```

**Key principle**: The expected value is always **derived from the target**, not invented. If a mock intercepts the call, the test must still assert that the connecting value would correctly reach the target.

Each contract becomes a **mandatory assertion** in at least one test case. Contracts not covered by user-provided Directions are auto-added under a "Contract Verification" direction (no user confirmation needed — these are structural correctness checks, not behavioral choices).

---

## 3. Direction (爆破方向)

AI must target "Contract Fragility" specified by the user. Every integration test plan must include a Direction.

**How to obtain Direction:**
1. Check if the user provided Direction in the `understand` output or conversation context. If found, use those directly.
2. If no Direction is found, **analyze and recommend** based on HLD and `understand` output, then STOP:

   **Analysis process:**
   a. Read the Module Interaction Flow from HLD (or Affected Files from `understand` if no HLD).
   b. For each module boundary / edge, identify the specific risk category:
      - **Prop Drilling Failure** — handler or data passed through layers may not trigger correctly
      - **Context Desync** — shared state update may not propagate to all consumers
      - **Conditional Rendering** — mount/unmount may lose state or render stale content
      - **Data Transform Mismatch** — data shape may mutate incorrectly across module boundary
      - **Error Propagation** — error from inner module may not surface correctly to outer module
   c. Output **concrete, context-specific** candidate directions with module names and interaction details:

   ```
   Based on HLD / source analysis, these integration directions are relevant:

   ☐ 1. [ParentForm → ChildInput] Prop Drilling — does onSubmit handler correctly receive validated form data?
   ☐ 2. [AuthContext → Dashboard] Context Desync — does Dashboard re-render when token refreshes?
   ☐ 3. [TaskList → TaskItem] Conditional Rendering — does empty list correctly unmount all TaskItems?
   ...

   Please select which directions to include, or add your own.
   ```

   **Rules for candidate generation:**
   - Every candidate MUST reference specific module names from HLD / source code — no generic descriptions.
   - Each HLD edge should produce at least one candidate direction.
   - Keep candidates concise: `[ModuleA → ModuleB] Category — one-sentence risk description`.
   - If the codebase context is insufficient to generate specific candidates, fall back to asking the user to describe their worries directly.

**Do NOT proceed until the user confirms at least one Direction.**

---

## 4. The "No UI Mocking" Iron Rule (External Only)

> **Principle**: Integration tests prove components mesh. Mocking components defeats the purpose.

- **Prohibited**: Do NOT mock any child components or Internal Dependencies (as classified in HLD Module Boundaries). Every internal module must be rendered/called for real.
- **Allowed**: Mock ONLY External Boundaries (network, DB, third-party APIs, parent-provided props/callbacks — as classified in HLD Module Boundaries). No limit on the number of External Boundary mocks.
- **REFACTOR Trigger**: If you need to mock an Internal Dependency to make the test work, **STOP**. Flag as REFACTOR_REQUIRED — the module boundary is wrong. Do not write the test.

---

## 5. Behavioral Assertions (Physical Outcomes)

> **Principle**: Assert what the user sees, not internal wiring.

- **Prohibited**: Testing `props` or `internal state` directly. Assertions must use testing-library query and matcher APIs (`getByText`, `getByRole`, `toHaveTextContent`, `toBeVisible`, etc.) to verify user-visible results. Direct access to the render tree's internal structure (`.children`, `.props`, `.type`, `.parent`) constitutes internal state inspection and is forbidden, even when the accessed value appears to represent visible content.
- **Required**: Testing **DOM Side-Effects** — what changes in the rendered output.
  - Correct: `expect(screen.getByText('New Task')).toBeVisible()` after clicking a child's button.
- **Prohibited as primary assertion**: `toHaveBeenCalled()` alone. Must pair with a DOM outcome assertion.

### 5b. Mock Function Call Assertions (mandatory when an API call function is mocked)

When any API call function is mocked, every test that triggers it **MUST assert all arguments**, not just some:

1. **Connecting value** (typically the first argument, e.g., URL path) — verify it would correctly reach the target module.
2. **Payload** (typically the second argument, e.g., request options) — verify method + body fields.

**Rationale**: Asserting only `toHaveBeenCalledOnce()` or only the payload misses connecting value errors (e.g., wrong path), which cause runtime failures but pass in tests because the mock doesn't validate the connecting value.

```typescript
// ❌ Incomplete — only asserts payload, ignores connecting value
expect(mockApiFn).toHaveBeenCalledOnce();
expect(calledOptions.body.key).toBe('value');

// ✅ Complete — asserts both connecting value and payload
expect(mockApiFn).toHaveBeenCalledOnce();
expect(mockApiFn.mock.calls[0][0]).toBe('/expected/path');
expect(calledOptions.body.key).toBe('value');
```

### 5d. Assertion Value Derivation (mandatory)

For each assertion's expected value, execute this checklist:

1. **Derive from requirement** — the expected value must come from the AC/understand description, not from reading what the implementation code currently produces.
2. **Cross-check against mock inputs** — if the expected value equals any mock input unchanged, this is a §5 violation signal. Ask: "Does this module combine/transform the input with other data (e.g., other state, config, safe area insets)?" If yes, the expected value must reflect that transformation.
3. **State the derivation** — add a comment above the assertion showing how the expected value was calculated from the requirement:

```typescript
// ❌ Mock-as-Output — expected value equals mock input unchanged
vi.mock('react-native-safe-area-context', () => ({
  useSafeAreaInsets: () => ({ bottom: 48 }),
}));
// keyboard mock height = 300
expect(onKeyboardOverlayChange).toHaveBeenCalledWith(300); // just echoes the mock

// ✅ Requirement-derived — expected value reflects the module's transformation
// requirement: scroll amount = dialog push amount = keyboardHeight + bottomInset
// 300 (mock keyboard) + 48 (mock safe area bottom) = 348
expect(onKeyboardOverlayChange).toHaveBeenCalledWith(348);
```

### 5c. Trigger Fidelity (mandatory when HLD exists)

> **Principle**: A test's trigger must be the **immediate cause** of the asserted outcome as defined in the HLD flow — not an earlier step in the chain.

When the HLD defines a multi-step event sequence (A → B → C → D), and the test asserts the outcome of step D:
- The trigger MUST be step C (the immediate preceding event that causes D).
- The trigger MUST NOT be step A or B (earlier steps that are only indirect preconditions).

**How to apply:**
1. For each test case, locate the asserted outcome in the HLD flow.
2. Trace backward to the **immediate preceding step** that directly causes that outcome.
3. That step is the trigger. Set up all prior steps as preconditions, but the trigger is only the immediate cause.

**FORBIDDEN**: Collapsing multiple HLD steps into one — asserting a later outcome triggered by an earlier event skips intermediate steps and hides integration bugs in the skipped steps.

**Test Plan enforcement:** Each test case MUST include a `Trigger (HLD Step)` reference identifying the specific HLD flow step that serves as the trigger. If the trigger cannot be traced to an HLD step, the test case is invalid.

---

## 6. Coverage (User-Driven)

Integration test cases are **defined by the user**. AI does NOT auto-generate integration tests — it translates user-specified Directions into concrete test cases.

- **Direction Coverage** (primary): Every user-provided Direction MUST have at least one test targeting it. Only these are included in the test plan by default.
- **AC Gap Check**: After mapping Directions to test cases, check if any AC ID from `understand` remains uncovered. For each uncovered AC, apply the **Scope Filter** from §1:

  - **Cross-module behavior** (function calls other modules) → valid integration test candidate. List in integration gap.
  - **Single-module logic** (input validation, format checking, boundary guards that short-circuit before calling any other module) → **unit test scope**. Collect separately for unit test supplementation.

  Output format:

  > **Integration gaps** (cross-module, can add to this plan): [AC-XX, AC-YY]
  > **Unit test scope** (single-module, will be covered by supplementary unit tests): [AC-ZZ]
  >
  > Should I add integration tests for the cross-module gaps? The unit-scope ACs will be included in a supplementary unit test plan automatically.

  **STOP and wait for user response.** Do NOT add uncovered AC tests without explicit user confirmation.

- **Path Coverage**: Cover orchestration flows implied by the confirmed test cases only.

- **State Propagation Coverage** (mandatory, auto-generated): When an interaction modifies a state value, scan ALL UI locations that consume that state. For each consumer:
  1. If the consumer is already covered by a Direction test, skip.
  2. If not covered, auto-generate a test case for that consumer.
  3. If the state is a toggle (like/unlike, add/remove), generate both forward and reverse cases per consumer.
  4. If the interaction involves an async call (API), generate one rollback test verifying state reverts on failure.

  These cases are added automatically — no user confirmation needed. List them in the test plan under a "State Propagation" direction.

---

## 7. Traceability

Every test case MUST map to:
- An **AC ID** from `understand` output
- A specific **Direction** (from §3)
- A concrete **artifact** (component or container from HLD or source code)

---

## 8. Test File Location

`__tests__/integration/[feature]/[name].test.ts`

---

## 9. Test Plan Output Format

```
## Test Plan

**Requirement Summary:** [1-3 sentences]
**Test Type:** integration
**Test file:** `__tests__/integration/[feature]/[name].test.ts`
**API Source:** HLD | Source Code
**Directions:** [list of user-provided directions]

### HLD Edge Contracts (auto-extracted from Module Interaction Flow)

| HLD Edge | Contract Type | Expected Value |
|---|---|---|
| [moduleA → moduleB] | [connecting value type] | [derived from target module] |

### Test Cases

| # | Test Name | Direction (爆破方向) | Covers (AC ID) | Contract Assertions | Artifact | Mock Count | Setup Complexity |
|---|---|---|---|---|---|---|---|
| 1 | [Imperative Action] | [Human-defined worry] | AC-XX | [which contracts are asserted] | `ParentComponent` | 1 (Hook only) | Med |
```

**Rules:**
- Every HLD Edge Contract MUST appear in the "Contract Assertions" column of at least one test case.
- If an edge contract is not covered by any user-provided Direction, auto-add it to the first relevant test case under a "Contract Verification" direction.
- Connecting values with dynamic segments MUST be verified with actual values in assertions, not patterns.

---

## 10. Writing Rules

- One `it()` block per plan row. Every row, zero omissions.
- Any `it()` not in the plan MUST be removed or justified as a new plan row.
- Any function/method call not defined in HLD or source code is a failure. If a function exists in HLD but its return type or parameter type is missing, follow the HLD gap detection rule in testcase SKILL.md Step 2 — flag it, do NOT invent the type.
- Write test code only — zero implementation code.
- Every assertion MUST follow §5 Behavioral Assertions rules.
- No `any` casting to bypass API contracts.
- **No implementation guessing**: Each assertion MUST target exactly one expected behavior. Do NOT write fallback assertions that accept multiple possible implementations (e.g., checking `data-pending || opacity !== '1' || aria-busy`). If the expected DOM output is not specified in the test plan, choose the assertion that best matches the AC's described behavior (e.g., `aria-busy` for loading state, `role` attributes for semantic structure) and let the implementation conform to it — this is TDD, tests drive implementation.
- **Exact value assertions**: Use `toBe` / `toEqual` with precise expected values. Do NOT use `toContain`, `toMatch`, or partial matchers when the full expected value is known or derivable from HLD constants.
