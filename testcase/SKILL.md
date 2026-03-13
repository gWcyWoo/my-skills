---
name: testcase
description: Use when writing test cases. Auto-recommends integration/E2E test types from context, designs test plan, writes test code. Unit tests only on explicit request.
---

# Test Case Workflow

## Skip Conditions

Do NOT invoke if the change involves no behavioral change: pure CSS, documentation, config, or file rename without logic change.

---

## Step 0: Determine Test Types

### Explicit argument provided

If the user passed an explicit argument (`/testcase integration`, `/testcase e2e`, or both), use those types directly. Load the corresponding rules file(s) and proceed to Step 1.

### No argument provided — Auto-recommend from context

When no argument is given, analyze the confirmed `understand` output and HLD to recommend test types:

1. **Review context**: Read the Requirements Analysis (Acceptance Criteria, Affected Files) and HLD (Module Boundaries, Interaction Flow, Interfaces) from the current conversation.

2. **Evaluate integration and e2e** against these criteria:

   | Type | Recommend when | Skip when |
   |---|---|---|
   | **integration** | Multiple modules interact; HLD shows cross-module data flow or orchestration; container/hook coordinates multiple concerns | Change is isolated to a single pure function/hook with no module interaction |
   | **e2e** | User-facing flow spans multiple pages/steps; critical path (auth, payment, form submission); HLD shows navigation or multi-step interaction | Change is purely internal logic with no visible UI impact; no page navigation involved |

3. **Output recommendation using one of these exact formats, then STOP**:

   **Both recommended:**
   ```
   Based on the requirements and HLD, I recommend:

   ✅ **integration** — [one-sentence reason referencing specific HLD modules/flows]
   ✅ **e2e** — [one-sentence reason referencing specific user flows]

   **Please confirm the test types before I proceed to design test plans.**
   ```

   **One recommended, one skipped:**
   ```
   Based on the requirements and HLD, I recommend:

   ✅ **integration** — [reason]
   ⏭️ **e2e** — Skip: [reason why e2e is unnecessary for this change]

   **Please confirm the test types before I proceed to design test plans.**
   ```

   **Both skipped** (rare — e.g., pure utility with no UI or module interaction):
   ```
   Based on the requirements and HLD, neither integration nor e2e tests are warranted:

   ⏭️ **integration** — Skip: [reason]
   ⏭️ **e2e** — Skip: [reason]

   If you still want tests, please specify the type explicitly (e.g., `/testcase unit`).
   ```
   In this case, **workflow ends here** unless the user requests otherwise.

   **Do NOT proceed until the user confirms.**

4. **Unit tests** — Do NOT recommend unit tests in Step 0. Unit tests are auto-generated as a **supplement** in Step 1: after integration/e2e test plans are designed, any AC whose behavior is single-module logic (not cross-module collaboration) and remains uncovered by integration/e2e will be collected for a unit test plan. See §6 AC Gap Check in each type file for details.

### After confirmation

For each confirmed test type, read the corresponding rules file:
- `unit` → Read `~/.claude/skills/testcase/unit.md`
- `integration` → Read `~/.claude/skills/testcase/integration.md`
- `e2e` → Read `~/.claude/skills/testcase/e2e.md`

If multiple types are confirmed, load all corresponding rules files and produce a test plan for each type in Step 1.

---

## Step 1: Design Test Plan

### Binding Inputs (mandatory — locate and directly reference, do NOT re-interpret)

Before designing, locate these exact artifacts from the current conversation. If any artifact is missing, ask the user and STOP.

| Artifact | Source | Used For |
|---|---|---|
| Acceptance Criteria (AC-01, AC-02, ...) | `understand` output | Traceability — every test case maps to an AC ID |
| Module Boundaries table | HLD output | Mock boundary identification (External Boundary column = what to mock) |
| Module Interaction Flow table | HLD output | Edge contract extraction, test case derivation |
| Interfaces / Function Signatures | HLD output | API contracts for assertions |

**FORBIDDEN**: Re-interpreting, summarizing, or expanding these artifacts. Use the exact content as written. If the HLD says module A calls module B with input X, the test plan must reflect that — not a re-derived version of the interaction.

### Design Process

1. Locate and directly reference the Binding Inputs listed above.
2. Follow the **Input Discovery** section in each loaded type file to identify API contracts.
3. Apply the **Coverage**, **Mock Rules**, **Traceability**, and all other rules from each loaded type file.
4. **Reverse Coverage Check**: After forward-mapping Flows to test cases, verify completeness by checking HLD Interfaces in reverse:
   - For each field in the HLD Interface definitions, confirm at least one test case asserts or exercises that field.
   - Any uncovered field = gap. Trace back: does the field have an AC? Does it have a Flow? If both missing, report as an HLD-AC inconsistency in the test plan output. If a Flow exists but was filtered (e.g., `Side Effect`), annotate which test type covers it.
5. **Mock Boundary Coverage Rule**: A test case can only claim to cover an AC/Flow if the mock boundary allows verification of the full behavior described by that AC/Flow. If the mock intercepts calls at layer X, the test can only verify the caller side of X — the callee side (everything behind the mock) is not verified by this test. Example: if mock is at `fetchRouteApi`, the test verifies client-side behavior (correct URL, correct rendering of response) but NOT the route handler → server function → backend chain behind it. Behavior not verified by this test MUST be marked as a coverage gap requiring a separate test with a different mock boundary.
6. Output the test plan using the **Test Plan Output Format** defined in each loaded type file. If multiple types, output each plan under a separate heading (`## Integration Test Plan`, `## E2E Test Plan`).

**STOP.** Output exactly:
> **Please confirm this test plan before I proceed to write test code.**

Do NOT make any tool calls after the test plan. If the user requests changes, revise and ask again.

---

## Step 1b: Supplementary Unit Test Plan (auto-triggered)

After integration/e2e test plans are confirmed, check if any ACs were marked as **"unit test scope"** during the AC Gap Check in Step 1. If yes:

1. Read `~/.claude/skills/testcase/unit.md` to load unit test rules.
2. For each unit-scope AC, design test cases following the unit test rules. These test **single-function, single-module logic** (validation, format checking, boundary guards, etc.).
3. Output the unit test plan under a `## Supplementary Unit Test Plan` heading.
4. No additional user confirmation needed for the unit plan — it was already implicitly approved when the user confirmed the integration/e2e plan that identified these ACs as unit scope.

**Priority**: Unit tests are supplementary. They fill coverage gaps that integration/e2e cannot reach. They do NOT replace or duplicate integration/e2e test cases.

---

## Step 2: Write Test Code

### Source of Truth

The **confirmed test plan** (from Step 1) is the sole input for writing test code. The test plan was derived from HLD and `understand` artifacts, which have already resolved any ambiguity in the original spec.

**FORBIDDEN**: Re-reading or re-interpreting the original spec/requirements to inform test code. If the HLD and test plan say X, write X — even if the original spec could be read differently. The HLD is the authoritative contract; the spec is history.

### Process

1. Load test standards. Skip any file already in conversation context.

   | Condition | File to Read |
   |---|---|
   | Any project | `~/.claude/shared-rules/test.md` |
   | Vue (`vue` in dependencies) | `~/.claude/shared-rules/vuejs.test.md` |
   | TypeScript (`.ts`/`.tsx` files) | `~/.claude/shared-rules/typescript.test.md` |

2. Write tests following the **Writing Rules** in each loaded type file. Every trigger, assertion, and setup must trace back to the confirmed test plan — not to the original spec.
   - **HLD gap detection**: If test code requires a type, interface, or return shape not defined in the HLD or source code, do NOT assume it. Flag it as an HLD gap, state the assumption explicitly in a comment, and report it in the correspondence table. The test must not silently make design decisions that belong to the HLD.
3. **Path deviation rule**: If the actual file path differs from the test plan (e.g., existing directory structure conflicts with planned path), do NOT silently change it. Explicitly state the deviation and reason in the correspondence table output (e.g., `Plan: __tests__/unit/task-my/ → Actual: __tests__/unit/ui/task-my/ — follows existing directory convention`).
4. Output a correspondence table mapping each plan row to its `it()` block.
5. **Lint gate (MANDATORY)**: Run `lint` on the written test file(s). If errors exist, fix them immediately — do NOT defer to the `code` phase. Common issues: incorrect type assertions (`as X` needs `as unknown as X`), unused imports, mismatched mock return types. Repeat until zero errors.

**Do NOT run tests.** The `tdd` workflow handles test execution.

**STOP.** Output exactly:
> **Test code is ready. Confirm to proceed with implementation via `code` skill.**

If the user confirms, invoke the `code` skill **using the Skill tool** to begin implementation. If the user requests changes, revise and ask again.
