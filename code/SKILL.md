---
name: code
description: Use when implementing code after requirements are confirmed. Loads project-specific standards and implements with traceability when HLD exists.
---

# Code Workflow

## Step 1: Load Project Standards

Determine project type by checking `package.json` dependencies and file extensions of the files to be created/modified. For each matching condition, check whether the file's content is already present in the current conversation context (loaded by a prior skill such as `hld`). Read ONLY the files whose content is NOT already in context.

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

## Step 1b: Read Reference Code

From the HLD's Affected Files list (or `understand` output if no HLD exists), select 1–2 existing source files that are most structurally similar to the files that will be created or modified. Read them.

**Selection criteria** (pick the file that matches the most criteria):
- Same file role: if creating a `container.tsx`, read an existing `container.tsx` from another feature
- Same module type: if creating a custom hook, read an existing `hooks.ts` from another feature
- Same layer: if modifying a route handler, read an existing `route.ts`

**Purpose**: These files are the **concrete pattern reference** for implementation. When a rule states an abstract principle, the reference code shows the exact pattern this project uses to fulfill that principle. Implementation in Step 2 SHOULD follow the structural patterns observed in the reference code (naming conventions, file organization, module composition style) — but only when they do not conflict with HLD contracts. See Step 2b priority order for conflict resolution.

If no structurally similar file exists in the project (e.g., entirely new module type), skip this step.

---

## Step 1c: Compile Implementation Checklist

Extract from ALL loaded rules (Step 1 + any rules already in context from prior skills) ONLY the items that are directly relevant to the current task's Affected Files and HLD design. Output a compact, numbered checklist with a maximum of 15 items.

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

Locate these exact artifacts from the current conversation. If any artifact is missing and there is no HLD, fall back to the user's original request — but if an HLD was produced and confirmed, it is the authoritative source.

| Artifact | Source | Used For |
|---|---|---|
| Acceptance Criteria (AC-01, AC-02, ...) | `understand` output | Scope — only implement what ACs require |
| Affected Files | `understand` output | Which files to create/modify |
| Interfaces / Function Signatures | HLD output | Implementation contracts — signatures must match exactly |
| Module Boundaries table | HLD output | File/module structure and dependency direction |
| Module Interaction Flow table | HLD output | Orchestration logic and connecting values between modules |

**FORBIDDEN**: Re-interpreting, summarizing, or expanding these artifacts. Implement what the HLD defines — not a re-derived version. If the HLD says module A is at path X with signature Y, implement exactly that.

If NONE of the above exist in conversation, ask the user and STOP:

> What should I implement? Please describe the requirements or point me to the relevant files.

### 2b. Write Code

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

### 2e. Verification Gate (MANDATORY)

Run ALL of the following before declaring implementation complete:

1. **Tests**: `npx vitest run 2>/dev/null` — all tests (integration, e2e, unit) must pass. Fix ALL failures, including pre-existing ones not caused by this task.
2. **Lint**: `lint 2>/dev/null` — zero errors. Fix ALL errors, including pre-existing ones not caused by this task.

Repeat until both commands report zero failures/errors. Do NOT declare implementation complete with any test failure or lint error outstanding.
