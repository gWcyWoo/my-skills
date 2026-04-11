---
name: spec
description: Requirement elicitation through structured conversation. Guides users to produce complete, versioned spec documents covering UI, interaction, flow, data, states, constraints, boundaries, architecture, and dependencies.
---

# Spec — Requirement Elicitation & Management

The primary function is **requirement elicitation through conversation** — turning vague ideas into structured, complete spec documents. The secondary function is incremental management of those specs over time.

## When to Use

- User describes a new feature, bug, or change request
- User wants to add requirements to an existing spec
- User wants to discuss and clarify requirements before implementation

## Process

### Step 0: Determine Context

Ask the user: **Is this a new spec or an update to an existing one?**
- If existing: ask for the spec file path (e.g., `specs/community/v1/post.spec.md`). Read it. Proceed to Step 5 (Incremental Update).
- If new: ask for the feature area and version (e.g., "community post, v1"). This determines the directory: `specs/{area}/v{n}/`. Proceed to Step 1.

**Tool loading (automatic — do not ask the user):**
- If the user's description references existing code (e.g., "like the feedback upload") → invoke `my-explore-0` skill to examine current implementation before starting elicitation
- If the requirement is vague or exploratory → invoke `superpowers:brainstorming` skill to help clarify direction
- Load tools as needed during elicitation, not only at the start

### Step 1: Requirement Elicitation (Core Function)

Guide the conversation to fill all dimensions. Do NOT ask all dimensions at once — start with what the user provided, identify gaps, and ask only about the missing ones.

**Dimensions checklist:**

| Dimension | What to establish | Example questions |
|-----------|------------------|-------------------|
| **UI** | Layout, sizing, colors, typography, design reference | "Where does this element appear? What size? Any design reference?" |
| **Interaction** | User actions, triggers, feedback, gestures | "What happens when user clicks/taps? Any loading feedback?" |
| **Flow** | Step-by-step operation sequence, happy path | "Walk me through the complete user journey step by step" |
| **Data** | Source, format, storage, API contracts | "Where does the data come from? What fields? How is it stored?" |
| **States** | Initial, loading, empty, error, success, disabled | "What does the user see before any data loads? On error?" |
| **Constraints** | Limits, validation rules, permissions | "Max count? Size limit? Format restrictions? Who can access?" |
| **Boundaries** | Edge cases, error handling, recovery | "What if network fails? Duplicate submission? Concurrent edits?" |
| **Architecture** | Module reuse, component organization, hook/service structure, relationship with existing modules | "Reuse existing hook or create new? Same API endpoint? Where does state live?" |
| **Dependencies** | Existing code to reference/reuse, APIs needed | "Any existing feature to reference? Which API endpoints?" |

**Elicitation rules:**

1. **Start from the user's description** — extract what's already provided, map to dimensions.
2. **Ask about gaps, not everything** — if the user already described the UI, don't ask about UI. Ask about what's missing.
3. **Group related questions** — ask 2-3 related questions per turn, not 8 at once.
4. **Use the codebase** — if the user references existing code ("like the feedback upload"), use `my-explore-0` to examine that code and confirm the pattern.
5. **Confirm understanding** — after each round, summarize what you've captured and ask "Is this correct? Anything to adjust?"
6. **Don't invent requirements** — only capture what the user confirms. If a dimension is intentionally not specified, mark it as "Not specified — to be determined during implementation."

### Step 2: Write Spec

After all dimensions are established, write the spec document.

**For new spec:** Write `specs/{area}/v{n}/{feature}.spec.md`

**For existing spec:** Update the relevant sections in the existing file.

**Spec document format:**

```markdown
# {Feature} Spec

## Meta
- **Area**: {area}
- **Version**: v{n}
- **Created**: {date}
- **Last Updated**: {date}

## Changelog

| Date | Type | Sections Affected | Procedure | Description |
|------|------|-------------------|-----------|-------------|
| {date} | New Feature | UI, Interaction, Data | {name} | {one-line summary} |

## UI

### {Section Name}
{Layout, sizing, colors, typography details}
{Design reference link if available}

### {Section Name}
...

## Interaction

### {Section Name}
{User action → system response pairs}

## Flow

### {Flow Name}
{Step-by-step sequence}
1. User does X
2. System responds with Y
3. ...

## Data

### {Data Entity}
{Fields, types, source, storage}

## States

| Component | Initial | Loading | Empty | Error | Success |
|-----------|---------|---------|-------|-------|---------|
| {name} | {description} | {description} | {description} | {description} | {description} |

## Architecture
- **Module reuse**: {Which existing modules/hooks/components to reuse}
- **New modules**: {What new modules to create, if any}
- **State management**: {Where state lives — local hook, global store, etc.}
- **API**: {Which endpoints, reuse existing or new}

## Constraints
- {Constraint 1}
- {Constraint 2}

## Boundaries / Edge Cases
- {Edge case 1}: {How to handle}
- {Edge case 2}: {How to handle}

## Dependencies
- {Dependency 1}: {What is referenced/reused}
```

### Step 3: User Confirmation

Present the completed (or updated) spec to the user:

> Spec written to `{spec_path}`.
>
> Please review the spec. You can:
> 1. **Request changes** — tell me what to adjust, and we'll update the spec
> 2. **Discuss next requirement** — add another feature/bugfix to this spec
> 3. **Proceed to implementation**:
>    - **understand-0** — run lightweight requirement analysis, then choose next step
>    - **auto-tdd** — fully automated pipeline (auto-testcase + auto-code parallel → verify, zero intervention; requires understand-0 first)

Wait for user selection:

- User requests changes → go back to Step 1 with the feedback, update the spec
- User wants to discuss next requirement → go back to Step 5 (Incremental Update) since the spec is already loaded
- User selects `understand-0` → create procedure directory (Step 4), then invoke the `understand-0` skill
- User selects `auto-tdd` → create procedure directory (Step 4), then invoke the `understand-0` skill; after it completes, invoke the `auto-tdd` skill with the procedure directory path

### Step 4: Create Procedure Directory

Before invoking understand-0 or auto-tdd:

1. Generate a short name (≤20 chars, kebab-case) from the changelog entry description
2. Create directory: `{spec_dir}/procedure/{YYYY-MM-DD}-{name}/`
3. Store as `procedure_dir`
4. Add the procedure directory path to the changelog entry

Pass to the next skill:
- `procedure_dir`: the created directory path
- `spec_path`: the spec file path (replaces requirement.md — the skill reads the spec directly)

### Step 5: Incremental Update (when updating existing spec)

When the user adds a requirement to an existing spec:

1. **Classify the change type**: New Feature | Bug Fix | Enhancement | Refactoring
2. **Locate affected sections** — which dimensions of the spec are affected?
3. **Elicit the new requirement** — apply Step 1 (Requirement Elicitation) to the new requirement only. Use the existing spec as context — ask only about dimensions that are missing or unclear for the NEW change, not for the entire spec.
4. **Update spec sections** — modify the relevant sections to reflect the new state. The spec body should always represent the **current complete truth**, not a diff.
5. **Append changelog entry** — record the change with date, type, affected sections, and description.
6. Proceed to Step 3 (User Confirmation).

**Conflict detection**: If the new requirement contradicts an existing spec section, flag it explicitly:

> **Conflict detected**: The new requirement "{X}" contradicts the existing spec section "{Y}" which states "{Z}". How should we resolve this?

Do NOT silently overwrite — always surface conflicts for user resolution.

## Rules

1. **User is the authority** — never invent requirements. If unsure, ask. If the user says "not needed", mark as "N/A".
2. **Spec body = current truth** — the spec body always represents the latest complete state. Historical changes are in the changelog only.
3. **One spec per feature scope** — a spec covers a coherent feature area (e.g., "Post Page", "User Profile"). Don't split into micro-specs per change.
4. **Changelog is append-only** — never modify or delete changelog entries.
5. **Procedure directories are created by spec** — downstream skills do not create them.
