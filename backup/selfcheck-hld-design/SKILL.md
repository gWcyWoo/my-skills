---
name: selfcheck-hld-design
description: Use after HLD design is complete, before requesting user confirmation. Dispatches Codex for independent audit, then self-iterates fixes until zero issues.
---

# HLD Design Self-Check

Independent audit of HLD output before user confirmation. This is a critical gate — the HLD serves as the sole contract for parallel test and code implementation.

## When to Use

After completing HLD Step 2 (Design), before presenting Step 4 (Output) to the user.

## Process

### Step 1: Prepare Inputs

Collect these three artifacts:
1. **Requirement Output** — The confirmed `understand` output (requirements analysis with acceptance criteria)
2. **Draft HLD** — The current HLD output (interfaces, signatures, modules, flow)
3. **CLAUDE.md path** — The project's CLAUDE.md file path for architecture rules

### Step 2: First Audit via Codex

Read the audit prompt template from `~/.claude/skills/selfcheck-hld-design/audit-prompt.md`.

Invoke the `codex` skill with `sandbox: read-only`. Construct the Codex prompt by combining:
- The full audit prompt template
- The three inputs from Step 1 substituted into the `[Requirement Output]`, `[Target HLD]`, and `[Architectural Rules]` sections

**Codex command template:**

```bash
codex exec \
  --model gpt-5.3-codex \
  --config model_reasoning_effort="medium" \
  --sandbox read-only \
  --skip-git-repo-check \
  --full-auto \
  2>/dev/null \
  "$(cat <<'PROMPT'
<AUDIT_PROMPT_TEMPLATE with inputs substituted>
PROMPT
)"
```

### Step 3: Process Codex Result

Parse the Codex output for **Status** and **Violations**.

- **PASS with 0 violations** → Go to Step 5
- **FAIL with violations** → Go to Step 4

### Step 4: Fix-and-Self-Review Loop

For each violation reported by Codex:

1. **Fix the HLD** — Modify the draft HLD to address the violation according to the suggested fix
2. **Scoped self-review** — ONLY verify that each reported violation has been correctly fixed. Do NOT expand audit scope beyond the reported issues.
   - For each Codex violation ID, confirm: Is the fix applied? Does the fix resolve the issue without introducing a new violation of the SAME category?
   - **Scope boundary**: If a fix is correct, move on. Do not re-audit unrelated parts of the HLD.
3. **If a fix introduces a new issue** — Fix that specific regression and re-verify it only
4. **If all fixes verified** → Go to Step 5

**Self-review rules:**
- Review ONLY the changed portions of the HLD — not the entire document
- Check ONLY whether each Codex-reported violation is resolved
- Do NOT flag new issues that Codex did not report — Codex already performed the exhaustive audit
- Output a simple checklist: `[violation ID] — Fixed: Y/N`

### Step 5: Present to User

Once zero issues confirmed, present the final HLD to the user for confirmation.

## Decision Summary

```
Codex Audit → PASS (0 issues) → Present HLD to user
Codex Audit → FAIL → Fix HLD → Self-review → 0 issues? → Present HLD to user
                                            → Still issues? → Fix again → Self-review → ...
```

**Never present an HLD with known issues to the user.**
