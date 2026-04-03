---
name: code
description: Use when implementing code after requirements are confirmed. Delegates isolated execution through my-subagent and enforces project-specific standards and traceability when HLD exists.
---

# Code Workflow

## Code Navigation

When you need to explore the codebase (find files, read implementations, check patterns), open `~/.agents/skills/my-explore/SKILL.md` first if not already loaded. Follow its methodology for all code navigation.

## Evidence-First Rule

During implementation and while repairing failures from verification commands, do **not** guess at fixes.

If a code change does not satisfy the expected behavior, or if any verification step fails, gather fresh evidence before the next edit. Use the failing command's output, a narrower repro, verbose flags, or targeted diagnostic instrumentation as appropriate to the failure mode. Then use that evidence to identify the failure point before making the next code change.

This is a mandatory rule. Repeated blind edits without new evidence are a workflow violation.

## Step 0: Delegate Through My-Subagent

Before launch, create `{procedure_dir}/audit/` if it does not already exist.

Open `~/.agents/skills/my-subagent/SKILL.md` and follow it.

Pass these parameters only:
- `task_prompt`: the exact child prompt below
- `agent_type`: `default`
- `model`: `gpt-5.4`
- `reasoning_effort`: `medium`

**Child `task_prompt` must contain only:**
1. The procedure directory path
2. Instruction: "First, open `~/.agents/skills/my-explore/SKILL.md` and follow it to load code navigation methodology."
3. Instruction: "Read `~/.agents/skills/auto-code/SKILL.md`. Skip Step 0 and Step 0b. Follow Steps 1–2 exactly. Use only `{procedure_dir}/hld.md` as your implementation authority. Do NOT read `requirement.md`, `understand.md`, test files, or any skill file besides `my-explore` and this `auto-code` skill — reading tests contaminates your implementation with test-specific patterns. After all required verification passes, return with `STATUS: COMPLETE`. Include the Implementation Checklist (Step 1c), traceability tables (Step 2c), and checklist verification (Step 2d) in your output — they will be reviewed independently."

**Do NOT add** implementation hints or code suggestions. The task derives everything from the procedure files and HLD contracts.

**Metrics Recording**: After every delegated child completion for this skill, check whether the task response includes usable usage metadata (for example `total_tokens`, `duration_ms`). If it does, append a row to `{procedure_dir}/metrics.md`. Create the file with header on first write; append rows on subsequent writes. If the current task response does not expose these fields, skip metrics recording for that completion. Metrics are optional and must never block the skill flow.

**Save the delegated child agent ID immediately** — store it as `code_task_id` BEFORE any status handling.

Let `my-subagent` own observability, liveness, resume mechanics, and child-lifecycle management. Follow `my-subagent` exactly. Only terminal `STATUS:` drives the workflow here.

**Handle task result:**

- **STATUS: COMPLETE** → Extract the author's Implementation Checklist (Step 1c) and traceability tables (Step 2c/2d) from the task output. Write them to `{procedure_dir}/audit/code-checklist.md`. Then proceed to Step 0b (Review).
- **STATUS: NEEDS_CLARIFICATION** → Forward questions to the user, then resume through `my-subagent` with a minimal resume bundle:
  - The procedure directory path
  - The same core instructions from Step 0
  - `Resume reason: user clarification`
  - The exact user answers
  - The same explicit model settings from Step 0: `model: "gpt-5.4"`, `reasoning_effort: "medium"`
  Save the new task ID, wait for terminal completion through `my-subagent`, and parse the restarted output again until STATUS: COMPLETE.

### Step 0b: External Review

Invoke `/Users/Woo/.agents/skills/review/SKILL.md` once with:
- `rules_path`: `/Users/Woo/.agents/skills/auto-code/self-check.rules.md`
- `files`: `{procedure_dir}/hld.md`, `{procedure_dir}/audit/code-checklist.md`, `{procedure_dir}/audit/code-self-check.md`, plus the new/modified implementation files
- `output_path`: `{procedure_dir}/audit/code-review.md`

The reviewer returns either `STATUS: PASS — 0 issues fixed`, `STATUS: PASS — X issues fixed`, or `STATUS: ISSUES_FOUND — X issues could not be fixed`. Do not re-run the reviewer after this result.

If the reviewer returns `STATUS: ISSUES_FOUND`, report the unrepaired blocker set to the orchestrator and stop. The review workflow already attempted direct fixes.

## Step 1: Load Project Standards

Determine project type by checking `package.json` dependencies and file extensions of the files to be created/modified. Read the matching rule files:

| Condition | File to Read |
|---|---|
| TypeScript (`.ts`/`.tsx` files) | `~/.agents/shared-rules/common/typescript.md` |
| Any frontend (`.vue`/`.tsx`/`.jsx` files) | `~/.agents/shared-rules/frontend/architecture.md` |
| Vue (`vue` in dependencies) | `~/.agents/shared-rules/frontend/vue3.md` |
| React (`react` in dependencies) | `~/.agents/shared-rules/frontend/reactjs.md` |
| Next.js (`next` in dependencies) | `~/.agents/shared-rules/frontend/nextjs.md` |
| Next.js fullstack (`next` + database operations) | `~/.agents/shared-rules/frontend/nextjs-fullstack.md` |
| Any backend (non-frontend `.ts`/`.js` files) | `~/.agents/shared-rules/backend/ddd.md` |
| Express (`express` in dependencies) | `~/.agents/shared-rules/backend/express.md` |
| MongoDB (`mongoose`/`mongodb` in dependencies) | `~/.agents/shared-rules/backend/mongodb.md` |

---

## Step 1b: Reference Code Patterns

From the HLD's Affected Files list (or `understand` output if no HLD exists), identify 1–2 existing source files that are most structurally similar to the files that will be created or modified. Use the code navigation tools to retrieve key symbols (component, hook, handler) from these files — do NOT read entire files.

**Selection criteria** (pick the file that matches the most criteria):
- Same file role: if creating a `container.tsx`, find an existing `container.tsx` from another feature
- Same module type: if creating a custom hook, find an existing `hooks.ts` from another feature
- Same layer: if modifying a route handler, find an existing `route.ts`

**Purpose**: These symbols are the **concrete pattern reference** for implementation. When a rule states an abstract principle, the reference code shows the exact pattern this project uses to fulfill that principle. Implementation in Step 2 SHOULD follow the structural patterns observed in the reference code (naming conventions, file organization, module composition style) — but only when they do not conflict with HLD contracts. See Step 2b priority order for conflict resolution.

If no structurally similar file exists in the project (e.g., entirely new module type), skip this step.

---

## Step 1c: Compile Implementation Checklist

Extract from ALL loaded rules (Step 1) ONLY the items that are directly relevant to the current task's Affected Files and HLD design. Output a compact, numbered checklist with a maximum of 15 items.

**Relevance filter**: Determine which constructs the code will contain by inspecting the HLD artifacts (not by guessing):
- **Interfaces / Function Signatures** → identify language constructs (async functions, hooks, route handlers, etc.)
- **Module Boundaries table** → identify module types (component, hook, server function, route handler)
- **Affected Files** → identify file roles by extension and path

A rule item is relevant if the HLD artifacts show the code will contain the construct the rule governs. Do NOT guess based on task description alone — derive from HLD.

**Output format** (output this checklist IMMEDIATELY before Step 2 — it must be the last content before code writing begins):

```
✅ Implementation Checklist:
1. [Specific, actionable rule item — not a restatement of the rule title, but the concrete constraint]
2. [...]
...
```

**Mandatory item** (always include when HLD has a Module Interaction Flow):
- Every cross-module reference (URL, import, endpoint) MUST be derivable from the target module's actual location or spec definition. Verify the value, not just the existence.

**Constraint**: Every item in this checklist is a hard requirement. After writing code in Step 2, every item MUST be satisfiable by the written code. Any item that is NOT satisfied is a blocker — fix the code before proceeding to traceability.

---

## Step 2: Implement

### 2a. Locate Binding Inputs (mandatory — do NOT re-interpret)

Locate these exact artifacts from `understand.md` and `hld.md`. The HLD is the authoritative source. If no HLD exists (no-logic change), use `understand.md` alone — it contains ACs and Affected Files.

| Artifact | Source | Used For |
|---|---|---|
| Acceptance Criteria (AC-01, AC-02, ...) | `understand` output | Scope — only implement what ACs require |
| Affected Files | `understand` output | Which files to create/modify |
| Interfaces / Function Signatures | HLD output | Implementation contracts — signatures must match exactly |
| Module Boundaries table | HLD output | File/module structure and dependency direction |
| Module Interaction Flow table | HLD output | Orchestration logic and connecting values between modules |

**FORBIDDEN**: Re-interpreting, summarizing, or expanding these artifacts. Implement what the HLD defines — not a re-derived version. If the HLD says module A is at path X with signature Y, implement exactly that.

### 2b. Write Code

**Read restriction**: When modifying existing source files, read only the specific lines you are about to edit (use line range). Use the code navigation tools to understand code before editing — do NOT read entire files for comprehension. For new files, create them directly with the available file-editing tools.

**Source of Truth**: The confirmed HLD is the sole architectural authority. Once HLD is confirmed, the original spec/requirements are history — they have been consumed and resolved by the HLD. Do NOT re-read or re-interpret the original spec to make implementation decisions. If the HLD and original spec could be read differently, follow the HLD.

**Flow Sequence Fidelity**: When the HLD defines a multi-step interaction flow (A → B → C → D), implement the steps in that exact causal order. Do NOT collapse steps, reorder them, or substitute one step's output as another step's trigger. Each step in the HLD flow must have a corresponding implementation that receives input from its immediate predecessor — not from an earlier step in the chain.

**Per-file HLD contract extraction (MANDATORY when HLD exists)**: Before writing each file, extract every HLD constraint that applies to this file and list them explicitly:

| HLD Dimension | Extract |
|---|---|
| Function Signatures | Parameter types, return type for every function in this file |
| Module Boundaries | Internal Dependencies, External Boundary for this module |
| Flow table | Every row where this module appears as Caller or Callee — note the Input and Expected Output |
| Design Decisions | Any decision that names or constrains this module |

This extraction brings HLD constraints to the foreground before writing. When reference code patterns (from Step 1b) conflict with any extracted HLD constraint, the HLD wins — reference code is a structural guide, not an architectural authority.

Implement according to the Binding Inputs located in 2a. The code MUST satisfy all of the following (in priority order — higher number overrides lower when they conflict):
1. The structural patterns from the reference code in Step 1b (when available) — lowest priority
2. The Implementation Checklist from Step 1c (every numbered item)
3. The HLD contracts (interfaces, signatures, module boundaries) — exact match, not approximate — **highest priority**

If implementation gets stuck, or if a later verification step shows the change still does not satisfy the contracts or tests, pause and gather fresh evidence first. Use the failing command's output, a narrower repro, verbose flags, or targeted diagnostic instrumentation as appropriate to the failure mode. Then use that evidence to drive the next edit.

### 2c. Traceability (only when HLD exists)

If an HLD exists in context, output THREE traceability checks after writing:

**Forward traceability** — every HLD element has an implementation:

```
| HLD Element | Implemented In | Status |
|---|---|---|
| [Interface/Function/Flow step] | [file:function] | ✅ / ❌ |
```

Every HLD element must be ✅. Any ❌ is a blocker — implement the missing element before proceeding.

**Reverse traceability** — every implementation block traces back to HLD:

```
| File | Code Element | HLD Element | Status |
|---|---|---|---|
| container.tsx | renders FilterSection | HLD Flow step 3 | ✅ |
| container.tsx | renders <header> block | ??? | ❌ REMOVE |
```

Any unmapped item is scope creep — remove it before proceeding.

**Flow edge traceability** — verify the HLD Module Interaction Flow's **edges**, not just nodes. For each edge (moduleA → moduleB), identify the **connecting value** (the data that crosses the boundary: URL path, import path, function argument, API endpoint) and verify its correctness.

```
| HLD Edge | Connecting Value Type | Expected | Actual | Status |
|---|---|---|---|---|
| [moduleA → moduleB] | [URL / import / param / endpoint] | [derived from HLD or target module's location] | [actual value in code] | ✅ / ❌ |
```

**Derivation rules:**
- The expected value of a connecting value is derived from the **target module**, not invented. For example, if moduleB is a file at a certain path, the URL/import that connects to it must be derivable from that path.
- Checking only "module exists" without verifying "the connecting value correctly points to that module" is insufficient and MUST NOT be marked ✅.
- Any mismatch is a **blocker** — fix before proceeding.

### 2d. Checklist Verification

Verify the written code against every item in the Implementation Checklist from Step 1c. Output:

```
| # | Checklist Item | Satisfied By | Status |
|---|---|---|---|
| 1 | [item text] | [file:line or code element] | ✅ / ❌ |
```

Every item MUST be ✅. Any ❌ is a blocker — fix the code before declaring implementation complete.

### 2e. Internal Self-Check (MANDATORY)

Run `/Users/Woo/.agents/skills/self-check/SKILL.md` with the following parameters:
- `rules_path`: `/Users/Woo/.agents/skills/auto-code/self-check.rules.md`
- `files`: `{procedure_dir}/hld.md`, `{procedure_dir}/audit/code-checklist.md`, plus every implementation artifact produced under `{procedure_dir}/output` (e.g., the files modified/created by the delegated child)
- `output_path`: `{procedure_dir}/audit/code-self-check.md`

**Handle result:**
- `STATUS: PASS` → proceed to the verification gate.
- `STATUS: ISSUES_FOUND` → the internal self-check found issues it could not repair automatically. Surface the blocker report and stop.

### 2f. Verification Gate (MANDATORY)

Run the project's verification commands in this order before declaring implementation complete:

1. **Unit + integration verification**: run the project's unit/integration test command(s). If the project has no unit/integration tests, record that explicitly.
2. **E2E verification**: detect the platform first. If `@playwright/test` appears in `devDependencies`, run `npx playwright test`. If `react-native` appears in `dependencies`, run `maestro test .maestro/`. Otherwise, run any documented e2e command(s) the repo exposes. If no e2e suites or commands exist, record that explicitly.
3. **Static verification**: run the project's lint and typecheck command(s), or the closest equivalent checks available in the project.

Repeat until every applicable verification step passes. Do NOT declare implementation complete with any outstanding test, lint, or typecheck failure.

When a verification command fails, do **not** jump directly to a guess-based code edit. First gather fresh evidence from the failing command, a narrower repro, verbose flags, or targeted diagnostic instrumentation, rerun the failing command to confirm the actual failing path, then apply the smallest root-cause fix and rerun the command.

### 2g. HLD_MISMATCH Handling

If you implement exactly what `{procedure_dir}/hld.md` specifies but downstream tests or the orchestrator expect different behavior, do not unilaterally match the tests. Instead:

1. Document the contradiction by writing `{procedure_dir}/audit/hld-mismatch.md` containing four pieces of evidence:
   - **HLD Reference** — the exact quote/section from `hld.md` that supports the implemented behavior.
   - **Implementation Evidence** — the relevant code snippet or explanation showing how the implementation matches the HLD.
   - **Test Expectation** — what the failing test or orchestration step expects instead.
   - **Contradiction Explanation** — why the two cannot both be true and what must change (either HLD or tests).
2. Return `STATUS: HLD_MISMATCH` and include the path to this file so the orchestrator can show it to the user and let them decide whether to change the HLD or the test.
3. Do not treat this as a code bug if you're truly following the HLD—if you cannot quote the HLD contract that supports your implementation, the discrepancy is your bug.
