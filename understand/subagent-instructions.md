# Understand Subagent Instructions

You are executing the analysis and design phases of the `understand` skill. Your job is to analyze the user's requirement, produce a Requirements Analysis document, and — for logic changes — produce an HLD design document.

**Output**: Write the analysis to `{procedure_dir}/understand.md`. For logic changes, also produce `{procedure_dir}/hld.md`.

## Inputs

You receive:
1. **Procedure directory path** — the directory containing `requirement.md`

Read `{procedure_dir}/requirement.md` to get the user's original request (and any referenced spec content).

## Code Navigation

The `my-explore` skill (loaded at session start) is your sole navigation methodology. Follow it exactly.

Analyze based on the current codebase state. Do not check git status, git diff, git log, or any version control state — these are irrelevant to requirements analysis and design.

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
5. **Existing Behavior Inventory** (MANDATORY): Examine the code being refactored and enumerate **every** user-observable behavior it currently implements. Each behavior must specify: trigger condition → expected result. Do NOT summarize as "all behaviors unchanged" — list them individually. Examples: "drag files onto drop area → files appear in list", "click delete button → file removed from list". Every behavior in this inventory becomes a behavioral AC.

**Async State Completeness** (all task types): For each client-side data fetch or async operation identified in the analysis, enumerate all user-visible UI states: initial/loading, success, error/empty. Each state that produces a distinct user-visible outcome must become a separate AC. Do NOT assume only the success path — loading indicators and error/empty states are user-observable behaviors.

After completing the analysis above, write **Ambiguities** (if any), then **Affected Files** (which files will be created or modified, and why), then **Acceptance Criteria** (AC-01, AC-02, ...) based on the analysis. ACs are written here, not deferred to a later step.

### Ambiguity Detection (MANDATORY)

Before writing ACs, scan the requirement for any item where:
- The meaning has multiple valid interpretations (e.g., `status: 1|0` — is 1=active/0=inactive, or 1=parsed/0=pending?)
- A term is used without definition (e.g., "返回 summary" — is summary a string excerpt, a structured object, or a full-text copy?)
- The requirement specifies a data shape but not its semantics (e.g., field names without value constraints)
- Two parts of the requirement imply contradictory behavior (e.g., "status: 1|0" but also "parsing fails" implies a third state)

If ambiguities are found:
1. Write an `### Ambiguities` section listing each one with a unique ID (AMB-01, AMB-02, ...)
2. For each ambiguity, state: what the requirement says, what the possible interpretations are, and what information is needed to resolve it
3. In any AC that depends on an unresolved ambiguity, append `(pending AMB-XX)` — this marks the AC as provisional
4. **Do NOT guess or pick an interpretation** — leave it explicitly unresolved

If the ambiguity is critical enough that the analysis cannot continue meaningfully, use the `NEEDS_CLARIFICATION` mechanism to ask the user. Otherwise, continue with the ambiguity marked and let the user resolve it during review.

Format:
```markdown
### Ambiguities

- AMB-01: `status: number, 1|0` — 1 and 0 represent what? Possible interpretations: (a) 1=active, 0=inactive; (b) 1=parsed, 0=pending; (c) boolean-style on/off. The requirement does not define the semantics of each value.
- AMB-02: "返回 summary" — what is summary? Possible: (a) first N characters of parsed content; (b) LLM-generated abstract; (c) structured object with key fields. Source and format undefined.
```

**Affected Files completeness**: For each file being modified, use `LSP findReferences` (if LSP is available) on the module's exports to discover test files that import it. If a test file exists and the modification changes the tested behavior, include the test file in Affected Files.

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
2. **Structural ACs**: One AC per structural goal of the refactoring (e.g., "all file-selection state and operations are encapsulated in a single dedicated module"). These are system-observable outcomes — verifiable by code inspection. They are valid because the purpose of refactoring IS structural change.

**Prohibited AC patterns** (all task types):
- Relative descriptions: "行为不变", "与之前一致", "不受影响" — these are not testable. Rewrite as positive statements of expected behavior.
- Blanket statements: "all interactions work the same" — enumerate each interaction as a separate AC.
- Negative-only criteria: "does not break X" — rewrite as "X produces [specific result] when [specific trigger]".

### Step 2b: Complexity Gate

After completing the analysis (Affected Files + ACs written), classify the change:

**No-logic change** — ALL of the following are true:
- No functions/methods are created or modified
- No state changes (component state, application state, global state)
- No data flow changes (API calls, data passing between modules, data transformations)
- No conditional logic added or modified
- Changes are limited to: CSS classes/styles, static text/labels, configuration constants, asset replacements

**Logic change** — Any change that does NOT meet ALL no-logic criteria above.

### Step 2c: AC Quality Self-Check (MANDATORY)

Before writing the output file, verify AC quality. For each AC, output a structured check covering FOUR dimensions — purity, prohibited patterns, observability, and traceability:

```
AC-01: "clicking the share icon opens a share panel with platform options"
  → file path? NO | function name? NO | tech choice? NO → Purity: PASS
  → relative description? NO | blanket statement? NO | negative-only? NO → Pattern: PASS
  → can a non-technical stakeholder verify by looking at the running app? YES (panel visibly opens) → Observability: PASS

AC-03: "loads post data from the backend API and displays a ranked card list"
  → Purity: PASS
  → Pattern: PASS
  → can a non-technical stakeholder verify by looking at the running app?
    "displays a ranked card list" YES, but "loads from backend API" NO (internal implementation) → Observability: FAIL
  → Rewrite: "on page load, a ranked list of daily trending post cards is displayed"
```

**Dimension 4 — Traceability (bidirectional):**

Forward: For each AC, cite the specific sentence or element in the requirement it traces to.
```
AC-01: "clicking the share icon opens a share panel with platform options"
  → Source: requirement says "点击分享图标，弹出分享面板" → Traceability: PASS

AC-08: "when hot topics API fails, an empty list is displayed"
  → Source: no sentence in requirement mentions API failure or empty list → Traceability: FAIL (overclaim — remove this AC)
```

Reverse: After all ACs are checked, scan the requirement for any distinct behavior or constraint that has NO corresponding AC.
```
Reverse scan:
  → "input/back, UI不变" → no AC covers preservation of input/back behavior → FAIL (add AC)
  → "暂时不处理返回数据的显示" → no AC captures this exclusion → FAIL (add exclusion AC)
```

Rules:
1. Every AC must appear in the check output. Skipping an AC = skipping the check = violation.
2. For Refactoring Structural ACs: skip the purity and observability checks (structural descriptions are verifiable by code inspection, not by running the app), but still check prohibited patterns. Traceability check still applies.
3. If any AC fails any dimension, fix it before writing the output file.
4. **Traceability is the highest-priority check** — an AC that passes purity, pattern, and observability but has no requirement source is an overclaim and must be removed. A requirement statement with no AC is a gap and must be covered.

Do NOT include self-check evidence in the output file — only the final analysis document.

## Write Output

Write `{procedure_dir}/understand.md` using the format that matches the complexity gate result:

### Logic change format

```markdown
## Requirements Analysis

**Task Type:** [New Feature | Bug Fix | Refactoring]
**Summary:** [One sentence]

### Analysis
[Structured answers from Step 2]

### Ambiguities
[If any — AMB-01, AMB-02, ... If none, omit this section entirely]

### Affected Files
- file1.tsx - [why]
- file2.ts - [why]

### Acceptance Criteria
- AC-01: [Criterion]
- AC-02: [Criterion] (pending AMB-01)
```

### No-logic change format

```markdown
## Requirements Analysis

**Task Type:** [New Feature | Bug Fix | Refactoring]
**Summary:** [One sentence]
**Complexity:** No-logic change (HLD skipped)

### Analysis
[Structured answers from Step 2]

### Ambiguities
[If any — AMB-01, AMB-02, ... If none, omit this section entirely]

### Affected Files
- file1.tsx - [why]

### Acceptance Criteria
- AC-01: [Criterion]
- AC-02: [Criterion]
```

After writing `understand.md`, check the complexity gate result:

- **No-logic** → Return to the main session immediately:
  ```
  STATUS: COMPLETE
  COMPLEXITY: no-logic
  ```

- **Logic** → Proceed to the HLD phase below.

## HLD Phase (logic changes only)

Read `~/.claude/skills/hld/SKILL.md` and follow its process exactly to produce `{procedure_dir}/hld.md`. You already have the code context from the analysis phase — CodeGraph, CocoIndex, and LSP results are still available.

After writing `hld.md`, return to the main session with:

```
STATUS: COMPLETE
COMPLEXITY: logic
```

## Ambiguity Handling

At any point during execution, if you encounter ambiguity that cannot be resolved from the codebase alone:

1. **Non-critical ambiguity** (analysis can continue meaningfully without resolution): Record it in the `### Ambiguities` section as AMB-XX, mark dependent ACs with `(pending AMB-XX)`, and continue execution. The user resolves it during review.

2. **Critical ambiguity** (analysis cannot continue — e.g., the entire feature scope depends on the interpretation): Stop execution and return:

```
STATUS: NEEDS_CLARIFICATION

COMPLETED_SO_FAR:
[Everything you've analyzed up to the ambiguity point]

QUESTIONS:
1. [Specific question with context for why it matters]
2. [Another question if needed]
```

The main session will forward your questions to the user and resume you with their answers.

**Do NOT guess or pick an interpretation for either type.** Non-critical ambiguities are marked, not resolved. Critical ambiguities halt execution.
