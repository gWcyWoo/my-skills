---
name: understand
description: Use when any code modification task is received, before design or implementation. Structures requirement analysis and HLD design in one pass.
---

# Requirements Understanding

Structured requirement analysis + HLD design. Must complete before any implementation.

## When to Use

Any task involving code changes: new features, bug fixes, refactoring.

## When NOT to Use

- Pure information queries (no code changes)
- Reading/exploring codebase
- Explaining existing code
- Configuration-only changes (no code logic), unless user explicitly requests analysis
- User explicitly instructs to skip analysis and code directly

## Process

### Step 1: Classify

Determine task type: **New Feature** | **Bug Fix** | **Refactoring**

### Step 2: Analyze

#### New Feature

1. **Interaction**: What user interactions? (click, input, drag, etc.)
2. **Pages/Components**: Which pages affected? What navigation flows?
3. **Data Flow**: What data is created, read, updated, deleted?
4. **Functional Goal**: What is the end-user outcome?
5. **Scope Boundary**: What is explicitly NOT included? Each excluded item must not conflict with the functional goals identified above — if excluding a file/module makes a functional goal unachievable, it must not be excluded.

#### Bug Fix

1. **Current Behavior**: What is happening now? (reproduction steps)
2. **Expected Behavior**: What should happen? (same structure as New Feature: interaction, pages, functional goal)
3. **Root Cause Hypothesis**: Where in the code might this originate?
4. **Impact Scope**: What else might be affected by the fix?

#### Refactoring

1. **Current State**: What is the current code structure?
2. **Target State**: What should it look like after?
3. **Motivation**: Why refactor? (performance, maintainability, etc.)
4. **Risk Assessment**: What might break?
5. **Existing Behavior Inventory** (MANDATORY): Read the code being refactored and enumerate **every** user-observable behavior it currently implements. Each behavior must specify: trigger condition → expected result. Do NOT summarize as "all behaviors unchanged" — list them individually. Examples: "drag files onto drop area → files appear in list", "click delete button → file removed from list". Every behavior in this inventory becomes a behavioral AC.

After completing the analysis above, write **Affected Files** (which files will be created or modified, and why) and **Acceptance Criteria** (AC-01, AC-02, ...) based on the analysis. ACs are written here, not deferred to a later step.

**Affected Files completeness**: For each file being modified, check whether existing test files cover that module (e.g., `__tests__/unit/**/module.test.ts`, `__tests__/integration/**/flow.test.ts`). If a test file exists and the modification changes the tested behavior, include the test file in Affected Files.

### AC Writing Rule

**AC sources**: ACs are derived from BOTH the initial requirement AND any user clarifications/constraints added during conversation. If the user specifies a behavioral constraint mid-conversation (e.g., "must not call API again", "use sessionStorage", "overwrite not append", "delete after read"), and that constraint describes a testable system behavior, it MUST become an AC — not just an HLD design decision.

Every AC MUST describe a **user-observable behavior or system-observable outcome**. ACs must NOT contain:
- File paths (e.g., "reuse src/components/share/index.tsx") — that is an HLD design decision
- Internal implementation choices (e.g., "use fetchRouteApi") — that is implementation
- Technology selections (e.g., "use Drawer component") — that is HLD

**Test (New Feature / Bug Fix)**: if a non-technical stakeholder cannot verify the AC by looking at the running application, it is not a valid AC. Rewrite it as observable behavior.

**Test (Refactoring)**: Behavioral ACs use the same test as above. Structural ACs use a different test: if a developer cannot verify the AC by inspecting the code structure (without running the application), it is not a valid structural AC.

**Refactoring exception**: For Refactoring tasks, ACs have TWO categories:
1. **Behavioral ACs**: One AC per behavior from the Existing Behavior Inventory. Each AC positively describes the expected behavior (trigger → result). These verify that refactoring preserves functionality.
2. **Structural ACs**: One AC per structural goal of the refactoring (e.g., "all file-selection state and operations are encapsulated in a single custom Hook"). These are system-observable outcomes — verifiable by code inspection. They are valid because the purpose of refactoring IS structural change.

**Prohibited AC patterns** (all task types):
- Relative descriptions: "行为不变", "与之前一致", "不受影响" — these are not testable. Rewrite as positive statements of expected behavior.
- Blanket statements: "all interactions work the same" — enumerate each interaction as a separate AC.
- Negative-only criteria: "does not break X" — rewrite as "X produces [specific result] when [specific trigger]".

### Step 3: Design

After completing the analysis, invoke the `hld` skill using the Skill tool. Pass no arguments — `hld` will consume the analysis output from the current conversation context. Wait for `hld` to complete and return its design output before proceeding to Step 3b.

Do NOT inline HLD content yourself. The `hld` skill has its own mandatory process (loading architecture rules, enforcing constraints). Skipping the Skill tool invocation bypasses those checks.

### Step 3b: Self-Check Gate (MANDATORY)

After `hld` returns, execute these checks before presenting to user. Each check MUST produce structured evidence in the exact format shown. "I checked and it looks fine" is NOT acceptable — output the structured comparison or it did not happen.

**Check 1: CLAUDE.md Rule Compliance**
1. Read the project's CLAUDE.md **in the repository root** using the `Read` tool (if not already in context). This is the project-specific CLAUDE.md, not the global `~/.claude/CLAUDE.md`. If no CLAUDE.md exists in the repository root, output "No project CLAUDE.md found — Check 1 N/A" and proceed to Check 2.
2. Identify every rule that constrains **code structure, data flow, API patterns, response types, URL conventions, or file organization**. Ignore workflow/process rules (e.g., "Phase 1: Requirements Understanding") — those do not apply to HLD content.
3. For each identified rule, output a structured comparison:
```
Rule: "[exact quote from CLAUDE.md]"
HLD element: "[exact quote from your HLD output that this rule applies to]"
Verdict: PASS / FAIL — [reason if FAIL]
```
4. If a rule has no corresponding HLD element (the rule's domain is not touched by this design), output: `Rule: "..." → Not applicable to this HLD — SKIP`
5. If any FAIL: fix the HLD element before proceeding.

**Check 2: Reused Module Interface Completeness**
1. For every component/module the HLD says to "reuse" or "integrate":
   - Use `LSP hover` on the component's export to extract its complete public interface (all props/params with types).
   - Output a field-by-field comparison:
```
Extracted interface (from LSP):
  - isOpen: boolean
  - onClose: () => void
  - fetchCallback: (id: string) => Promise<Partial<ShareInfo>>
  - invitation: { id, name, logo, shareText, shortLink, shareQRImgLink }

HLD defines:
  - isOpen: boolean ✓
  - onClose: () => void ✓
  - fetchCallback: MISSING ✗
  - invitation.shareQRImgLink: MISSING ✗
```
   - Any field marked ✗ = FAIL.
2. If any FAIL: update HLD interfaces before proceeding.
3. If HLD does not reference any reused modules: output "No reused modules — Check 2 N/A" and proceed.

**Check 3: Affected Files Sync**
1. List every file path that appears anywhere in the HLD output (Interfaces, Signatures, Module Boundaries, Flows).
2. List every file in the Requirements Analysis Affected Files section.
3. Output a two-column comparison:
```
HLD files                          | Affected Files list
-----------------------------------|-------------------
types.ts                           | ✓ listed
api/server/share.ts                | ✓ listed
constants.ts                       | ✗ NOT in Affected Files  ← FAIL
```
4. Any file in HLD but not in Affected Files = FAIL (add it).
5. Any file in Affected Files but not referenced anywhere in HLD = FAIL (justify or remove it).

**Check 4: AC Quality**
1. For each AC, output a structured check covering BOTH purity and prohibited patterns:
```
AC-01: "clicking the share icon triggers a share API call"
  → file path? NO | function name? NO | tech choice? NO → Purity: PASS
  → relative description? NO | blanket statement? NO | negative-only? NO → Pattern: PASS

AC-03: "上传行为不受影响"
  → Purity: PASS
  → relative description? YES ("不受影响") → Pattern: FAIL
  → Rewrite: "clicking upload button triggers sequential upload and clears file list"

AC-05: "reuse src/components/custom/share/index.tsx"
  → file path? YES → Purity: FAIL
  → Rewrite: "Share panel appears as a bottom drawer with 5 platform options"
  → Move "reuse src/components/custom/share/index.tsx" to HLD Design Decisions
```
2. Every AC must appear in the output. Skipping an AC = skipping the check = violation.
3. For Refactoring Structural ACs: skip the purity check (structural descriptions like "custom Hook" are allowed), but still check prohibited patterns.

**Check 5: Flow Table Completeness**

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
4. Missing row = FAIL. The HLD designer must have added the corresponding row — the checker does not determine whether failure is possible. Fix by adding the missing Flow row to the HLD.

Only after all 5 checks pass with structured evidence, proceed to Step 3c.

### Step 3c: Present Combined Output

Combine the requirements analysis (from Step 2) with the HLD design (returned by `hld` in Step 3) into the format defined in Step 4. Present to the user and ask:

> **Select next step:**
> 1. **code** — Confirmed. Proceed to implementation.
> 2. **testcase** — Confirmed. Generate test cases first, then implement.
> 3. **audit** — Run third-party audit (`understand-hld-check`) before proceeding.
> 4. **save** — Save HLD record to `.auto-tdd/` for quality analysis.

- User replies `1` / `code` (or equivalent: "确认", "ok", "没问题", "直接编码", "proceed") → invoke the `code` skill **using the Skill tool**.
- User replies `2` / `testcase` (or equivalent: "测试", "先写测试", "tdd") → invoke the `testcase` skill **using the Skill tool**.
- User replies `3` / `audit` (or equivalent: "审计", "review", "check") → invoke the `understand-hld-check` skill **using the Skill tool**. If violations are found, fix them per the skill's instructions, then re-present the updated output to the user with the same four options.
- User replies `4` / `save` (or equivalent: "保存", "记录", "save hld") → invoke the `save-hld-record` skill **using the Skill tool**. After saving, re-present the same four options so the user can continue.

**Do NOT execute skill logic inline.** Each skill has its own mandatory process (loading standards, checklists, traceability). Skipping the Skill tool invocation bypasses those checks.

Do NOT proceed without a user selection. If the user requests changes to the analysis or design instead of selecting an option, revise and re-present.

### Step 4: Output Format

The combined document presented in Step 3c MUST use this structure:

```
---
## Requirements Analysis

**Task Type:** [New Feature | Bug Fix | Refactoring]
**Summary:** [One sentence]

### Analysis
[Structured answers from Step 2]

### Affected Files
- file1.tsx - [why]
- file2.ts - [why]

### Acceptance Criteria
- AC-01: [Criterion]
- AC-02: [Criterion]

## High-Level Design

### Interfaces
[Interface definitions from HLD]

### Function Signatures
[Signatures with descriptions from HLD]

### Module Boundaries
[Module boundary table from HLD]

### Module Interaction Flow
[Interaction flow table from HLD]

### Design Decisions
[Key decisions and rationale from HLD]
---
```

### Step 5: Route

Execute the user's selection from Step 3c. All routing logic is defined in Step 3c — do not duplicate or override it here.
