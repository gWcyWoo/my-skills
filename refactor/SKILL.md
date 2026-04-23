---
name: refactor
description: Use when refactoring existing code to comply with project coding standards while delegating isolated execution through my-subagent. Reads code as the requirement, loads shared-rules as the target, and restructures without changing behavior.
---

# Refactor

Restructure existing code to comply with project coding standards. The current code defines the behavior (requirement); the shared-rules define the target structure. No new functionality is added.

## When to Use

- Code works but does not follow project conventions (naming, file structure, module boundaries, abstraction patterns)
- Prototype code needs to be brought up to production standards
- Caller explicitly requests refactoring without new requirements

## When NOT to Use

- New behavior or features are needed — use `u-0` first
- Code has bugs — fix bugs first, then refactor separately

## Inputs

The caller must provide:
- `files` — one or more file paths to refactor

## Process

### Step 1: Delegate Through My-Subagent

Open `~/.agents/skills/my-subagent/SKILL.md` and follow it.

Pass these parameters only:
- `task_prompt`: the exact child prompt below
- `agent_type`: `worker`
- `model`: `gpt-5.4`
- `reasoning_effort`: `medium`

**Child `task_prompt`:**

```
You are refactoring existing code to comply with project coding standards. The current code defines the behavior — preserve it exactly. No new functionality, no behavior changes.

FILES TO REFACTOR:
{files}

INSTRUCTIONS:
1. Open `~/.agents/skills/my-explore-0/SKILL.md` and follow it to load code navigation methodology.
2. Run the Verification Gate (code/SKILL.md Step 2e) BEFORE making any changes. Record the results as the baseline. This tells you which tests pass and which fail before your refactor.
3. Read `~/.agents/skills/auto-code/SKILL.md`. Skip Step 0 and Step 0b (do NOT dispatch another subagent or invoke review). Follow Steps 1, 1b, and 1c only:
   - Step 1: Load Project Standards — determine file types from the files to refactor, load matching shared-rules.
   - Step 1b: Reference Code Patterns — use the files to refactor as the "Affected Files" list. Find 1-2 existing files in the project that are structurally similar and already comply with the rules.
   - Step 1c: Compile Implementation Checklist — extract relevant rules into a numbered checklist (max 15 items). This checklist defines what "compliant" looks like.
4. For each file to refactor, use code navigation tools (codegraph_node, Probe MCP raw tools such as `search`/`query`/`extract`/`symbols`, and LSP) to understand its structure and identify violations against the Implementation Checklist.
5. Refactor the code to resolve all violations. Two hard constraints:
   - Preserve existing behavior exactly — same inputs, same outputs, same side effects. If unsure whether a change alters behavior, do not make it.
   - Do NOT modify any test files. Tests define the expected behavior. If a test fails after refactoring, fix the production code, not the test.
6. Run the Verification Gate again. Compare against the baseline:
   - Any test that was PASSING before but FAILS now — your refactor broke it. Fix the production code.
   - Any test that was FAILING before — still fix it by fixing production code (not the test). Pre-existing failures are not an excuse to skip.
   - ALL checks must pass with zero failures. Do not proceed until they do.
7. Output the Implementation Checklist with satisfaction status for each item, then return STATUS: COMPLETE.
```

**Save the delegated child agent ID immediately** — store it as `refactor_agent_id` before any status handling. This is the only child you resume directly.

### Step 2: Handle Result

Let `my-subagent` own observability, liveness, resume mechanics, and child-lifecycle management. Follow `my-subagent` exactly. Only `STATUS:` drives the workflow here.

- **STATUS: COMPLETE** → Present the checklist to the user. Done.
- **STATUS: NEEDS_CLARIFICATION** → Forward questions to the user, then follow `my-subagent`'s clarification/resume flow for `refactor_agent_id` using the user's answers.
