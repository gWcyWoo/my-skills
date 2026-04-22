# E2E Test Rules (L7 Direction-Based Edition)

## 1. Scope

End-to-end user flows: full page interactions, navigation, and API round-trips through the real stack. Focus on **user-visible behavior** and **physical layout integrity**.

**MANDATORY for Data Contract Regression direction**: Before writing any test, build a complete field-to-locator mapping table (`TypeField → Locator`). When HLD exists, derive the mapping from HLD UI layout contracts and type definition files — do NOT read component implementation files (see SKILL.md "Code Reading Boundaries"). When no HLD exists, read the component render tree to build the mapping. Use the locator priority defined in §6.1 to determine the best locator for each field. Every field that has a visible UI representation MUST have a corresponding assertion. Writing tests before this mapping is complete is forbidden.

---

## 2. Input Discovery

- **With HLD**: Use HLD-defined page routes, user flow descriptions, and UI layout contracts. The HLD is the sole contract. You may read type/interface definition files (e.g., `schema.ts`, `types.ts`) even if listed in Affected Files — they define contracts. You MUST NOT read files that contain function bodies or business logic. See SKILL.md "Code Reading Boundaries" for the full rule.
- **Without HLD**: Invoke `Skill(my-explore-0)` to load code navigation methodology, then use it on files from `u-0` → Affected Files. Identify page routes, navigation flows, form actions, layout components. These define the test targets.

---

## 3. Direction (爆破方向)

AI must not generate generic "Happy Path" tests. Every E2E test must target a human-defined **Direction** — a high-risk "broken" scenario.

**How to obtain Direction:**
1. Check if the user provided Direction in the `u-0` output or conversation context. If found, use those directly.
2. If no Direction is found, **analyze and recommend** based on HLD and `u-0` output, then STOP:

   **Analysis process:**
   a. Read the page routes, user flows, and UI layout contracts from HLD (or Affected Files from `u-0` if no HLD).
   b. For each user-facing flow / page, identify the specific risk category:
      - **Physical Conflict** — layout overlap, z-index issues, viewport overflow
      - **State Desync** — race conditions during navigation, hydration mismatch, stale data after route change
      - **Extreme Boundaries** — empty/null state, long-string overflow, network failure UI
      - **Navigation Integrity** — wrong redirect, broken back-button, query param loss
      - **Data Contract Regression** — API response shape change breaks rendered fields
   c. Output **concrete, context-specific** candidate directions with page/flow names and scenario details:

   ```
   Based on HLD / source analysis, these E2E directions are relevant:

   ☐ 1. [Login → Dashboard redirect] Navigation Integrity — does successful login redirect to /dashboard with session intact?
   ☐ 2. [TaskList page] Physical Conflict — does long task title overflow its container on mobile viewport?
   ☐ 3. [ProfileEdit → API save] Data Contract Regression — does the form render correctly if API returns optional fields as null?
   ...

   Please select which directions to include, or add your own.
   ```

   **Rules for candidate generation:**
   - Every candidate MUST reference specific pages, routes, or user flows from HLD / source code — no generic descriptions.
   - Each user-facing flow should produce at least one candidate direction.
   - Keep candidates concise: `[Page/Flow] Category — one-sentence risk scenario`.
   - If the codebase context is insufficient to generate specific candidates, fall back to asking the user to describe their worries directly.

**Do NOT proceed until the user confirms at least one Direction.**

---

## 4. Coverage (User-Driven)

E2E test cases are **defined by the user**. AI does NOT auto-generate E2E tests — it translates user-specified Directions into concrete test cases.

- **Direction Coverage** (primary): Every user-provided Direction MUST have at least one test targeting it. Only these are included in the test plan by default.
- **AC Gap Check**: After mapping Directions to test cases, check if any AC ID from `u-0` remains uncovered. For each uncovered AC, apply a **Scope Filter**:

  - **User-facing flow** (spans pages, navigation, visible interaction) → valid E2E test candidate. List in E2E gap.
  - **Internal logic** (validation rules, data transforms, single-module behavior with no UI impact) → **unit test scope**. Collect separately for unit test supplementation.

  Output format:

  > **E2E gaps** (user-facing flows, can add to this plan): [AC-XX, AC-YY]
  > **Unit test scope** (internal logic, will be covered by supplementary unit tests): [AC-ZZ]
  >
  > Should I add E2E tests for the user-facing gaps? The unit-scope ACs will be included in a supplementary unit test plan automatically.

  **STOP and wait for user response.** Do NOT add uncovered AC tests without explicit user confirmation.

- **Path Coverage**: Cover user-facing flows implied by the confirmed test cases only.
- Each test represents a **complete user journey** or a meaningful sub-journey.

---

## 5. Mocking Rules

- **Zero Mocking**: Tests run against the real application stack (Frontend + Backend + DB).
- **Exceptions**: Only external 3rd-party services (e.g., Payment Gateways, SMS) may use sandbox/test modes.
- **State Reset**: Every test flow must trigger a data cleanup/reset to ensure consistency between runs.

### 5b. Trigger Fidelity (mandatory when HLD exists)

> **Principle**: A test's trigger must be the **immediate cause** of the asserted outcome as defined in the HLD flow — not an earlier step in the chain.

When the HLD defines a multi-step user flow (A → B → C → D), and the test asserts the outcome of step D:
- The trigger MUST be step C (the immediate preceding event that causes D).
- The trigger MUST NOT be step A or B (earlier steps that are only indirect preconditions).

**How to apply:**
1. For each test case, locate the asserted outcome in the HLD flow.
2. Trace backward to the **immediate preceding step** that directly causes that outcome.
3. That step is the trigger. Set up all prior steps as preconditions, but the trigger is only the immediate cause.

**FORBIDDEN**: Collapsing multiple HLD steps into one — asserting a later outcome triggered by an earlier event skips intermediate steps and hides bugs in the skipped steps.

**Test Plan enforcement:** Each test case MUST include a `Trigger (HLD Step)` reference identifying the specific HLD flow step that serves as the trigger. If the trigger cannot be traced to an HLD step, the test case is invalid.

---

## 6. Element Locator & Assertion Rules

### 6.1 Element Locator Priority

Use the highest-priority locator that uniquely identifies the element. Only fall through to the next level when all higher-priority options are impossible.

| Priority | Method | Example | When to Use |
|---|---|---|---|
| 1 (highest) | **Role + Name** | `getByRole('button', { name: 'Submit' })` | Element has an accessible role and distinguishable name |
| 2 | **Label** | `getByLabel('Email address')` | Form elements with associated `<label>` |
| 3 | **Text** | `getByText('Save changes')` | Visible text is stable and unique on page |
| 4 | **Placeholder** | `getByPlaceholder('Search...')` | Input with placeholder, no label available |
| 5 (last resort) | **Alt / Title** | `getByAltText('User avatar')` | Images or elements with alt/title attributes |

**Rules:**
- **FORBIDDEN**: `data-testid`, `testID`, or any locator that requires modifying source code to support tests. E2E tests must work with the application as-is.
- Do NOT use CSS class selectors (`.btn-primary`) or structural selectors (`div > span:nth-child(2)`) — these are fragile and break on style/layout changes.
- For i18n projects where visible text changes by locale, prefer Role + Name (priority 1) over Text (priority 3).

### 6.2 Physical Assertion Rules

**Principle**: DOM existence does not equal functionality. Prefer assertions that prove visibility and interactivity.

- **Prefer**: `toBeVisible()`, `toBeEnabled()`, `toHaveScreenshot()` (when visual regression is configured).
- **Avoid**: `toBeInTheDocument()` as the sole assertion for proving an element works. It only proves DOM presence, not that the user can see or interact with it.
- **Exception**: `not.toBeInTheDocument()` is valid for verifying element removal or conditional rendering.

---

## 7. Traceability

Every test case MUST map to:
- An **AC ID** from `u-0` output
- A specific **Direction** (from §3)

---

## 8. Test File Location

`__tests__/e2e/[feature]/[name].test.ts` (or `.spec.ts` per project convention)

---

## 9. Test Plan Output Format

```
## Test Plan

**Requirement Summary:** [1-3 sentences]
**Test Type:** e2e
**Test file:** `__tests__/e2e/[feature]/[name].test.ts`
**API Source:** HLD | Source Code
**Directions:** [list of user-provided directions]

| # | Test Name | Direction (爆破方向) | Covers (AC ID) | Physical Assertions |
|---|---|---|---|---|
| 1 | [Action Description] | [Scenario from §3] | AC-XX | toBeVisible, toBeEnabled |
```

---

## 10. Writing Rules

- One `it()` or `test()` block per plan row. Every row, zero omissions.
- Any test not in the plan MUST be removed or justified as a new plan row.
- Write test code only — zero implementation code.
- Every element locator MUST follow §6.1 Locator Priority. `data-testid` is forbidden.
- Every assertion MUST follow §6.2 Physical Assertion Rules.
- **FORBIDDEN**: `page.waitForURL(pattern, { waitUntil: 'commit' })` when the test asserts page content after navigation. ALWAYS use the default `waitUntil: 'load'`.
