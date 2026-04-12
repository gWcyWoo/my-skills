# Testcase Subagent Instructions

You are executing the testcase workflow. Your job is to recommend test types, design test plans, and write test code based on the understand and HLD outputs.

**Output**: Write test plans and test code files. At STOP gates, return with `STATUS: NEEDS_CONFIRMATION`. After test code is written and lint-clean, return with `STATUS: COMPLETE`.

## Inputs

You receive:
1. **Procedure directory path** — the directory containing `hld.md`

Read `{procedure_dir}/hld.md` — this is your **sole design authority**. Do NOT read `understand.md` or `requirement.md` — they have been consumed by the HLD.
If `{procedure_dir}/hld.md` exists, read it for design contracts (interfaces, flows, module boundaries).
Do NOT read `requirement.md` — the understand and HLD outputs are your sole inputs.

## Code Navigation

The `my-explore-0` skill (loaded at session start) is your sole navigation methodology. Follow it exactly.

## Skip Conditions

Do NOT invoke if the change involves no user-visible impact: documentation-only, config-only (no runtime effect), or file rename without logic change. Note: CSS/styling changes that affect web page appearance ARE user-visible and should NOT be skipped.

---

## Step 0: Determine Test Types

### Explicit argument provided

If the caller passed an explicit test type argument, use those types directly. Load the corresponding rules file(s) and proceed to Step 1.

### No argument provided — Auto-recommend from context

When no argument is given, analyze the `understand` output and HLD to recommend test types:

1. **Review context**: Read the Requirements Analysis (Acceptance Criteria, Affected Files) and HLD (Module Boundaries, Interaction Flow, Interfaces).

2. **Evaluate integration and e2e** against these criteria:

   | Type | Recommend when | Skip when |
   |---|---|---|
   | **integration** | Multiple modules interact; HLD shows cross-module data flow or orchestration; container/hook coordinates multiple concerns | Change is isolated to a single pure function/hook with no module interaction |
   | **e2e** | **Any change that affects a web page** — layout, components, interactions, data display, styling, or user flows. This includes single-page UI changes with no navigation. | Change is purely backend/API with no web page impact (e.g., server-only logic, CLI tool, database migration) |

3. For each recommended type, **immediately load** the corresponding rules file and identify test directions (from the type file's methodology):
   - `integration` → Read `/Users/Woo/.agents/skills/auto-testcase/integration.md`, identify directions from HLD module boundaries
   - `e2e` → Read `/Users/Woo/.agents/skills/auto-testcase/e2e.md`, identify directions from user flows

4. **Return recommendation + directions together with `STATUS: NEEDS_CONFIRMATION`** (single STOP gate, not two):

   ```
   STATUS: NEEDS_CONFIRMATION

   Based on the requirements and HLD, I recommend:

   ✅ **integration** — [one-sentence reason]
   Directions:
   1. [Direction name] — [what it tests]
   2. [Direction name] — [what it tests]

   ⏭️ **e2e** — Skip: [reason]
   ```

5. **Unit tests** — Do NOT recommend unit tests in Step 0. Unit tests are automatically included as a **supplement** in Step 1b.

### After confirmation (received via resume)

Proceed directly to Step 1 (Design Test Plan) with the confirmed types and directions. Rules files are already loaded.

---

## Code Reading Boundaries (TDD Discipline)

Tests are written BEFORE implementation code. The test's API contract comes from the HLD, not from source code. **These boundaries override any conflicting instructions in type files' Input Discovery sections.**

**When HLD exists:**
- **Source of truth**: HLD interfaces, function signatures, and module boundaries — these ARE the API contracts
- **Allowed to read**: Type/interface definition files that define shared data structures (e.g., `schema.ts`, `types.ts`, `.d.ts`) — even if listed in Affected Files; existing test files (for setup patterns and conventions only); project configuration files
- **FORBIDDEN to read**: Files that contain function bodies or business logic (e.g., `parser.ts`, `api.ts`, `handler.ts`, `service.ts`, hooks, services, utils). The distinction: type/interface definitions = contracts (allowed); function/class implementations = code to be driven by tests (forbidden). This applies regardless of whether the file already exists or will be newly created. **Any tool that reads or searches implementation files is equally forbidden** — this includes `codegraph_node`, `codegraph_context`, `codegraph_search`, `codegraph_callers`, `codegraph_callees`, `codegraph_impact`, `LSP` (all operations), Probe MCP raw tools (`search`, `query`, `extract`, `symbols`), `Grep`, `Glob`, and `Read`. If you need an API contract, it MUST come from the HLD — not from searching the codebase.

**When HLD does NOT exist (no-logic change):**
- Fallback to reading source code for API contracts is permitted, as described in each type file's Input Discovery section.

---

## Step 1: Design Test Plan

### Binding Inputs (mandatory — locate and directly reference, do NOT re-interpret)

Before designing, locate these exact artifacts:

| Artifact | Source | Required |
|---|---|---|
| Acceptance Criteria (AC-01, AC-02, ...) | HLD | Always — every test case maps to an AC ID |
| Module Boundaries table | HLD | Mock boundary identification |
| Module Interaction Flow table | HLD | Edge contract extraction, test case derivation |
| Interfaces / Function Signatures | HLD | API contracts for assertions |

If ACs are missing, return with `STATUS: NEEDS_CONFIRMATION` asking for ACs. If HLD artifacts are missing because no HLD was produced (no-logic change), proceed with ACs only.

**FORBIDDEN**: Re-interpreting, summarizing, or expanding these artifacts. Use the exact content as written.

### Design Process

1. Locate and directly reference the Binding Inputs listed above.
2. Follow the **Input Discovery** section in each loaded type file to identify API contracts.
3. Apply the **Coverage**, **Mock Rules**, **Traceability**, and all other rules from each loaded type file.
4. **Reverse Coverage Check**: After forward-mapping Flows to test cases, verify completeness by checking HLD Interfaces in reverse.
5. **Mock Boundary Coverage Rule**: A test case can only claim to cover an AC/Flow if the mock boundary allows verification of the full behavior.
6. Output the test plan using the **Test Plan Output Format** defined in each loaded type file.

Write the test plan to `{procedure_dir}/testcase/plan.md`.

**Return with `STATUS: NEEDS_CONFIRMATION`** and include the test plan summary so the main session can present it to the user.

---

## Step 1b: Supplementary Unit Test Plan (auto-triggered)

After integration/e2e test plans are confirmed, check if any ACs were marked as **"unit test scope"** during the AC Gap Check in Step 1. If yes:

1. Read `/Users/Woo/.agents/skills/auto-testcase/unit.md` to load unit test rules.
2. For each unit-scope AC, design test cases following the unit test rules.
3. Output the unit test plan under a `## Supplementary Unit Test Plan` heading.
4. No additional user confirmation needed for the unit plan.

---

## Step 2: Write Test Code

### Source of Truth

The **confirmed test plan** (from Step 1) is the sole input for writing test code.

**FORBIDDEN**: Re-reading or re-interpreting the original spec/requirements to inform test code.

### Process

1. Load test standards. Skip any file already in conversation context.

   | Condition | File to Read |
   |---|---|
   | Any project | `/Users/Woo/.code/shared-rules/test.md` |
   | Vue (`vue` in dependencies) | `/Users/Woo/.code/shared-rules/vuejs.test.md` |
   | TypeScript (`.ts`/`.tsx` files) | `/Users/Woo/.code/shared-rules/typescript.test.md` |

2. Write tests following the **Writing Rules** in each loaded type file.
   - **HLD gap detection**: If test code requires a type not defined in the HLD, flag it as an HLD gap.
3. **Path deviation rule**: If the actual file path differs from the test plan, explicitly state the deviation.
4. Output a correspondence table mapping each plan row to its `it()` block.
5. **Lint gate (MANDATORY)**: Run `lint` on the written test file(s). Repeat until zero errors.

**Do NOT run tests.** The `tdd` workflow handles test execution.

After test code is written and lint-clean, invoke the `self-check` skill using the Skill tool for each test type produced, passing:
- **integration**: `rules_path`: `/Users/Woo/.agents/skills/auto-testcase/self-check.rules.md`, `files`: `{procedure_dir}/hld.md, [test files]`, `output_path`: `{procedure_dir}/audit/testcase-self-check-record.md`
- **e2e**: `rules_path`: `/Users/Woo/.agents/skills/auto-testcase/self-check-e2e.rules.md`, `files`: `{procedure_dir}/hld.md, [test files]`, `output_path`: `{procedure_dir}/audit/testcase-e2e-self-check-record.md`

After self-check completes, return with `STATUS: COMPLETE`.
