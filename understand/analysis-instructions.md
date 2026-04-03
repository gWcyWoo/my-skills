# Analysis Instructions

You are executing the analysis and design phases of the `understand` skill. Your job is to analyze the user's requirement, produce a Requirements Analysis artifact, and — for logic changes — produce an HLD design artifact.

**Output**: In persisted-file mode, write the analysis to `{procedure_dir}/understand.md`. For logic changes, also produce `{procedure_dir}/hld.md`. In conversation-first mode, present the same content in conversation and do not write files yet.

## Inputs

This file is used in two modes:

1. **Conversation-first understand mode** — when invoked from `/Users/Woo/.agents/skills/understand/SKILL.md` Step 1 before persistence, the user's conversation message is the requirement input. In this mode, ignore any `requirement.md` references and present the analysis in conversation instead of writing files.
2. **Persisted-file mode** — when a workflow has already created `{procedure_dir}/requirement.md`, read it before starting analysis.

## Code Navigation

The `my-explore` skill (loaded before this file) is your sole navigation methodology. Follow it exactly.

This file defines analysis steps only. It does not define, refine, or override any code-exploration tool choice, tool sequence, fallback rule, or shell rule. All code-exploration tool usage remains delegated to `my-explore`.

Analyze based on the current codebase state. Do not check git status, git diff, git log, or any version control state — these are irrelevant to requirements analysis and design.

**Do NOT inspect test-file bodies** (`*.test.*`, `*.spec.*`, `__tests__/**`, `*.e2e.*`, and similar test-runner config or fixture files) during requirements analysis. Test files are out of scope for analysis, even if `my-explore` later identifies a related test file that should be listed in Affected Files.

## Purpose & Method

**What this phase does**: Understand the user's requirement well enough to produce an HLD (High-Level Design). You are NOT implementing — you are building the understanding needed for design.

**Why you read code**: To learn the current state of the code that the requirement touches — existing interfaces, data shapes, module boundaries. This informs the HLD's design decisions.

**How to read code**:
1. Start from the requirement — identify the entry point (which file, which component, which function).
2. Follow only the call chain relevant to the requirement. Stop when you reach code that the requirement does not affect.
3. Before reading any file, ask yourself: "Does the requirement need me to understand this file?" If no, skip it.
4. **Budget**: For a bug fix, 5–10 file reads should be sufficient. For a new feature, 10–20. If you exceed this, you are likely exploring beyond scope.

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

After completing the analysis above, write **Ambiguities** (if any), then **Affected Files** (which files will be created or modified, and why), then **Acceptance Criteria** using the extractive process below.

### AC Generation: Extract, Don't Create

**Principle**: The requirement is a closed specification. ACs are extracted from it, not invented from domain knowledge. If the requirement doesn't mention it, it's not in scope.

**Process**:

1. **Enumerate** — List every distinct sentence in the requirement that describes a behavior, constraint, UI spec, exclusion, or preservation. Number them (R1, R2, ...).

2. **Convert** — For each R-number, write one AC that directly translates it into a testable statement. The AC must not add behaviors the sentence doesn't describe.

3. **Verify** — Every AC has an R-number. Every R-number has an AC. If a sentence cannot become an AC, it is an ambiguity (AMB-XX).

**Refactoring**: Behavioral ACs come from Existing Behavior Inventory (extract from code). Structural ACs come from the requirement's structural goals (extract from requirement). Same principle: extract, don't invent.

**Loading/error/empty states**: Only create ACs if the requirement **explicitly mentions** them (e.g., "show a loading indicator" -> AC). No mention -> no AC.

### Ambiguity Detection (during Enumerate step)

During Step 1 of AC Generation (Enumerate), scan each requirement sentence for:
- The meaning has multiple valid interpretations (e.g., `status: 1|0` — is 1=active/0=inactive, or 1=parsed/0=pending?)
- A term is used without definition (e.g., "return summary" — is summary a string excerpt, a structured object, or a full-text copy?)
- The requirement specifies a data shape but not its semantics (e.g., field names without value constraints)
- Two parts of the requirement imply contradictory behavior (e.g., "status: 1|0" but also "parsing fails" implies a third state)

If ambiguities are found:
1. Write an `### Ambiguities` section listing each one with a unique ID (AMB-01, AMB-02, ...)
2. For each ambiguity, state: what the requirement says, what the possible interpretations are, and what information is needed to resolve it
3. In any AC that depends on an unresolved ambiguity, append `(pending AMB-XX)` — this marks the AC as provisional
4. **Do NOT guess or pick an interpretation** — leave it explicitly unresolved

If the ambiguity is critical enough that the analysis cannot continue meaningfully, **STOP and ask the user**. Otherwise, continue with the ambiguity marked and let the user resolve it during review.

Format:
```markdown
### Ambiguities

- AMB-01: `status: number, 1|0` — 1 and 0 represent what? Possible interpretations: (a) 1=active, 0=inactive; (b) 1=parsed, 0=pending; (c) boolean-style on/off. The requirement does not define the semantics of each value.
- AMB-02: "return summary" — what is summary? Possible: (a) first N characters of parsed content; (b) LLM-generated abstract; (c) structured object with key fields. Source and format undefined.
```

**Affected Files completeness**: For each file being modified, use `my-explore` to identify any relevant test files or dependent files that should appear in Affected Files. If a test file exists and the modification changes the tested behavior, include the test file in Affected Files. Do not add tool-specific instructions here; `my-explore` decides the method.

### AC Writing Rule

**AC sources (closed set)**: ACs are extracted from exactly two sources — the requirement text and user clarifications during conversation. No other source is valid. Domain knowledge, engineering best practices, and "what a good system should do" are NOT AC sources — they belong in HLD design decisions, not in ACs.

Every AC MUST describe a **user-observable behavior or system-observable outcome**. ACs must NOT contain:
- File paths (e.g., "reuse path/to/existing-module") — that is an HLD design decision
- Internal implementation choices (e.g., "call a specific API helper") — that is implementation
- Technology selections (e.g., "use a specific UI component") — that is HLD

**Test (New Feature / Bug Fix)**: if a non-technical stakeholder cannot verify the AC by looking at the running application, it is not a valid AC. Rewrite it as observable behavior.

**Test (Refactoring)**: Behavioral ACs use the same test as above. Structural ACs use a different test: if a developer cannot verify the AC by inspecting the code structure (without running the application), it is not a valid structural AC.

**Refactoring exception**: For Refactoring tasks, ACs have TWO categories:
1. **Behavioral ACs**: One AC per behavior from the Existing Behavior Inventory. Each AC positively describes the expected behavior (trigger → result). These verify that refactoring preserves functionality.
2. **Structural ACs**: One AC per structural goal of the refactoring (e.g., "all file-selection state and operations are encapsulated in a single dedicated module"). These are system-observable outcomes — verifiable by code inspection. They are valid because the purpose of refactoring IS structural change.

**Prohibited AC patterns** (all task types):
- Relative descriptions: "behavior remains unchanged", "same as before", "unaffected" — these are not testable. Rewrite them as positive statements of expected behavior.
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

### Step 2c: AC Quality Self-Check (author-side, before writing output)

Before writing the output file, verify each AC against the four dimensions.

For each AC, verify:
1. **Purity** — no file paths, function names, or tech choices
2. **Pattern** — no relative descriptions, blanket statements, or negative-only criteria
3. **Observability** — a non-technical stakeholder can verify by looking at the running app (structural ACs: verifiable by code inspection)
4. **Traceability** — has an R-number (from requirement) or BI-number (from Existing Behavior Inventory)

If any AC fails → fix it before writing the output file.

After all ACs pass, run **gap detection** (mechanical):
1. Collect all R/BI numbers cited by ACs
2. Compare against the complete set of R-numbers (from Enumerate step) and BI-numbers (from Existing Behavior Inventory)
3. Gap = any R/BI number not cited by any AC → add an AC for it

Ensure ACs are clean before writing output.

## Write Output

Produce the Requirements Analysis artifact using the format that matches the complexity gate result. In persisted-file mode, write it to `{procedure_dir}/understand.md`. In conversation-first mode, present the same structure in conversation.

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
- path/to/file-a - [why]
- path/to/file-b - [why]

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
- path/to/file-a - [why]

### Acceptance Criteria
- AC-01: [Criterion]
- AC-02: [Criterion]
```

After producing the Requirements Analysis artifact, check the complexity gate result:

- **No-logic** → Analysis complete. Proceed to Step 2 of the `understand` skill.
- **Logic** → Proceed to the HLD phase below.

## HLD Phase (logic changes only)

Read `/Users/Woo/.agents/skills/hld/SKILL.md` and follow Steps 0-3 exactly, because the parent `understand` skill only delegates that HLD subset at this stage. In persisted-file mode, write the resulting HLD artifact to `{procedure_dir}/hld.md`. In conversation-first mode, present the same HLD content in conversation and do not write files yet. Use the analysis context you already built.

After producing the HLD artifact, analysis complete. Proceed to Step 2 of the `understand` skill.

## Ambiguity Handling

At any point during execution, if you encounter ambiguity that cannot be resolved from the codebase alone:

1. **Non-critical ambiguity** (analysis can continue meaningfully without resolution): Record it in the `### Ambiguities` section as AMB-XX, mark dependent ACs with `(pending AMB-XX)`, and continue execution. The user resolves it during review.

2. **Critical ambiguity** (analysis cannot continue — e.g., the entire feature scope depends on the interpretation): **STOP and ask the user** directly. Explain what you've analyzed so far and why the question matters. Wait for the user's answer, then continue the analysis.

**Do NOT guess or pick an interpretation for either type.** Non-critical ambiguities are marked, not resolved. Critical ambiguities halt execution until the user answers.
