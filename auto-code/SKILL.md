---
name: auto-code
description: Use when implementing code after requirements are confirmed. Loads project-specific standards and implements with traceability against HLD contracts.
---

# Code Workflow

## Code Navigation

When you need to explore the codebase (find files, read implementations, check patterns), invoke the `my-explore` skill via Skill tool first if not already loaded. Follow its methodology for all code navigation.

## Step 0: Dispatch Subagent

Launch an Agent subagent (general-purpose) to execute the implementation. This isolates implementation noise (rule loading, traceability tables, test/lint output) from the main session.

**Subagent prompt must contain:**
1. The procedure directory path
2. Instruction: "First, invoke the `my-explore` skill using the Skill tool to load code navigation methodology."
3. Instruction: "Read `~/.claude/skills/auto-code/SKILL.md` and follow Steps 1–2 exactly. Read the design from `{procedure_dir}/hld.md` — this is your **sole implementation authority**. Do NOT read `requirement.md` or `understand.md` — they have been consumed by the HLD. Do NOT read any test files (`*.test.*`, `*.spec.*`, `__tests__/**`) — test code is reviewed independently against the same HLD; reading tests contaminates your implementation with test-specific patterns (mock structures, assertion expectations) that diverge from the HLD contract, causing review failures. After all verification passes (vitest + e2e + lint — see Step 2e for details), return with `STATUS: COMPLETE`. Include the Implementation Checklist (Step 1c), traceability tables (Step 2c), and checklist verification (Step 2d) in your output — they will be reviewed independently. If you encounter a test failure that contradicts the HLD (your implementation follows the HLD but a test expects different behavior), return with `STATUS: HLD_MISMATCH` and describe the conflict — do NOT modify your implementation to match the test."

**Do NOT add** implementation hints or code suggestions. The subagent derives everything from the HLD contracts.

**Metrics Recording**: After every Agent dispatch or SendMessage resume returns, extract the `<usage>` block (total_tokens, tool_uses, duration_ms) and append a row to `{procedure_dir}/metrics.md`. Create the file with header on first write; append rows on subsequent writes.

**Save the code agent ID immediately** — the Agent tool returns an agent ID (e.g., `agentId: a1b2c3d4`). Save it as `code_agent_id` BEFORE checking the status. This is the ONLY agent you will resume directly. The review skill manages its own reviewer agent internally.

**Handle subagent result:**

- **STATUS: COMPLETE** → Extract the author's Implementation Checklist (Step 1c) and traceability tables (Step 2c/2d) from the code agent's output. Write them to `{procedure_dir}/audit/code-checklist.md`. Then proceed to Step 0b (Review).
- **STATUS: NEEDS_CLARIFICATION** → Forward questions to the user, resume subagent with `SendMessage(to: "<code_agent_id>", message: "<user's answers>")`. Use the agent ID (not name) to resume.
- **STATUS: HLD_MISMATCH** → The code agent's implementation follows the HLD but a test expects different behavior. Read `{procedure_dir}/audit/hld-mismatch.md` and present its content to the user. The user decides whether to fix the HLD or fix the test. After resolution, resume the code agent with the decision.

### Step 0b: Independent Review

Invoke the `review` skill **using the Skill tool**, passing these parameters:
- `procedure_dir`: the procedure directory path
- `rules_path`: `~/.claude/skills/auto-code/self-check.rules.md`
- `files`: `{procedure_dir}/understand.md, {procedure_dir}/hld.md, {procedure_dir}/audit/code-checklist.md`
- `output_path`: `{procedure_dir}/audit/code-self-check.md`

**Handle result:**

#### STATUS: PASS
All tables clean. Present the result to the user.

#### STATUS: ISSUES_FOUND
The reviewer found defects with severity breakdown (e.g., "0 CRITICAL, 1 MAJOR, 2 MINOR, 1 TRIVIAL").

1. **Resume the code agent** using `SendMessage(to: "<code_agent_id>", message: "Reviewer found these issues: <list issues>. Fix the code.")`
2. After fixes, extract the updated checklist/traceability from the agent's output and update `{procedure_dir}/audit/code-checklist.md`
3. Present the result to the user. Do NOT re-invoke the review — the self-check already caught the bulk of issues, and one review round is sufficient.

## Step 1: Load Project Standards

Determine project type by checking `package.json` dependencies and file extensions of the files to be created/modified. Read the matching rule files:

| Condition | File to Read |
|---|---|
| TypeScript (`.ts`/`.tsx` files) | `~/.claude/shared-rules/common/typescript.md` |
| Any frontend (`.vue`/`.tsx`/`.jsx` files) | `~/.claude/shared-rules/frontend/architecture.md` |
| Vue (`vue` in dependencies) | `~/.claude/shared-rules/frontend/vue3.md` |
| React (`react` in dependencies) | `~/.claude/shared-rules/frontend/reactjs.md` |
| Next.js (`next` in dependencies) | `~/.claude/shared-rules/frontend/nextjs.md` |
| Next.js fullstack (`next` + database operations) | `~/.claude/shared-rules/frontend/nextjs-fullstack.md` |
| Any backend (non-frontend `.ts`/`.js` files) | `~/.claude/shared-rules/backend/ddd.md` |
| Express (`express` in dependencies) | `~/.claude/shared-rules/backend/express.md` |
| MongoDB (`mongoose`/`mongodb` in dependencies) | `~/.claude/shared-rules/backend/mongodb.md` |

---

## Step 1b: Reference Code Patterns

From the HLD's Affected Files list, identify 1–2 existing source files that are most structurally similar to the files that will be created or modified. Use `codegraph_node(includeCode: true)` to retrieve key symbols (component, hook, handler) from these files — do NOT Read entire files.

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

Locate these exact artifacts from `hld.md`. The HLD is the **sole implementation authority**.

| Artifact | Source | Used For |
|---|---|---|
| Acceptance Criteria (AC-01, AC-02, ...) | HLD | Scope — only implement what ACs require |
| Affected Files | HLD | Which files to create/modify |
| Interfaces / Function Signatures | HLD | Implementation contracts — signatures must match exactly |
| Module Boundaries table | HLD | File/module structure and dependency direction |
| Module Interaction Flow table | HLD | Orchestration logic and connecting values between modules |

**FORBIDDEN**: Re-interpreting, summarizing, or expanding these artifacts. Implement what the HLD defines — not a re-derived version. If the HLD says module A is at path X with signature Y, implement exactly that.

### 2b. Write Code

**Read restriction**: When modifying existing source files, Read only the specific lines you are about to Edit (use line range). Use `codegraph_node(includeCode: true)` to understand code before editing — do NOT Read entire files for comprehension. For new files, use Write directly.

**Source of Truth**: The confirmed HLD is the sole architectural authority. Once HLD is confirmed, the original spec/requirements are history — they have been consumed and resolved by the HLD. Do NOT re-read or re-interpret the original spec to make implementation decisions. If the HLD and original spec could be read differently, follow the HLD.

**Flow Sequence Fidelity**: When the HLD defines a multi-step interaction flow (A → B → C → D), implement the steps in that exact causal order. Do NOT collapse steps, reorder them, or substitute one step's output as another step's trigger. Each step in the HLD flow must have a corresponding implementation that receives input from its immediate predecessor — not from an earlier step in the chain.

**Per-file HLD contract extraction (MANDATORY)**: Before writing each file, extract every HLD constraint that applies to this file and list them explicitly:

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

### 2c. Traceability

Output THREE traceability checks after writing:

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

### 2e. Self-Check

Invoke the `self-check` skill using the Skill tool, passing:
- `rules_path`: `~/.claude/skills/auto-code/self-check.rules.md`
- `files`: `{procedure_dir}/hld.md, {procedure_dir}/audit/code-checklist.md`
- `output_path`: `{procedure_dir}/audit/code-self-check-record.md`

### 2f. Verification Gate (MANDATORY)

Run ALL of the following in order before declaring implementation complete:

1. **Unit + Integration tests**: `npx vitest run 2>/dev/null` — all tests must pass. Fix ALL failures, including pre-existing ones.
2. **E2E tests** — detect platform and run the appropriate tool. Skip if no e2e test files exist in the project.
   - **Web** (has `playwright` in devDependencies): `npx playwright test 2>/dev/null`
   - **React Native** (has `react-native` in dependencies): `maestro test .maestro/ 2>/dev/null`
   - Fix ALL failures, including pre-existing ones.
3. **Lint**: `lint 2>/dev/null` — zero type errors. Fix ALL errors, including pre-existing ones.

Repeat until all three commands report zero failures/errors. Do NOT declare implementation complete with any test failure or lint error outstanding.

**When a test fails, diagnose before fixing:**

1. **Locate the HLD contract** — find the specific interface, signature, or Flow Expected Output in `hld.md` that governs the failing behavior.
2. **Compare implementation vs HLD** — does your code match the HLD contract? Check: function signature, parameter types, return type, async/state mutation order, module boundary.
3. **Decide:**
   - **Implementation deviates from HLD** → your bug. Fix your code to match the HLD. This is the common case.
   - **Implementation matches HLD exactly, but the test expects different behavior** → this is an `HLD_MISMATCH`. Before reporting, you MUST provide evidence:
     - Quote the HLD contract (exact text from hld.md)
     - Quote your implementation (show it matches)
     - Describe what the test expects (from the error output — do NOT read the test file)
     - Explain the contradiction

Only report `HLD_MISMATCH` after completing all 4 evidence steps. If you cannot quote an HLD contract that supports your implementation, it is your bug, not an HLD mismatch.

When reporting `HLD_MISMATCH`, write the evidence to `{procedure_dir}/audit/hld-mismatch.md`:

```markdown
## HLD Mismatch Report

### HLD Contract
> [exact quote from hld.md — section, flow ID, or signature]

### Implementation
> [quote your code that matches the HLD contract]

### Test Expectation
> [what the test error output says it expects — from vitest output, NOT from reading the test file]

### Contradiction
[one sentence explaining why the HLD contract and test expectation conflict]
```
