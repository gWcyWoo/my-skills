# Skill Writing Standard

This document is the **authoritative standard** for every `SKILL.md` (and skill-internal prompt file) in `~/.claude/skills/`. Any new or edited skill MUST conform.

The standard distills six prompting principles from Anthropic's official guidance, adapted to how skills are loaded and executed inside Claude Code.

---

## P0 — Hard Requirements

A skill file is **non-conforming** if any P0 is missing.

1. **Explicit goal, constraints, success criteria.** State *what* the skill must produce, *what it must not do*, and *how to know it is done*. No implicit "Claude figures it out."
2. **XML-tagged structure.** The skill body MUST use these tags (omit any that genuinely do not apply, but never inline their content into prose):
   - `<role>` — one short paragraph (1–3 sentences): who the executing agent is, where it runs (main session vs named subagent), and what it must NOT do. Anything longer belongs in `<context>`.
   - `<context>` — background, tool reference, domain knowledge. Long material goes here, near the top (length threshold defined in rule #3 below).
   - `<instructions>` — numbered, sequential steps. Each step is a single concrete action.
   - `<input>` — the variables / placeholders the caller must supply (use `{{NAME}}` syntax).
   - `<examples>` — 1–3 worked examples. At least one positive example. One labeled `BAD — do not do this` is encouraged.
   - `<output_format>` — the exact slots the agent must fill. File:line precision where applicable.
   - `<success_criteria>` — the conditions under which the task is considered complete. Include a stop rule.
   - `<final_reminders>` — P0 / P1 / P2 lines that re-state the most important constraints (P0 = hard rules, P1 = strong rules, P2 = key efficiency preferences worth surfacing). This is the *last* thing the agent reads, so put the things you most need it to remember after the rest of the file is digested.
3. **Long reference material lives in `<context>`.** Tool docs, rules, playbooks, and other background material **longer than ~5 lines** go in `<context>` near the top of the skill body, before `<instructions>`. Never bury a long reference block inside or after `<instructions>` — it pushes the actionable steps further from the agent's working memory.
4. **Caller-supplied placeholders live in `<input>`.** Variables the caller substitutes (e.g. `{{REQUIREMENT_SUMMARY}}`, `{{FILES}}`) go in the `<input>` block, positioned between `<instructions>` and `<examples>` per the template below. The user's runtime query arrives via the conversation, not via a file slot.
5. **Final P0/P1/P2 reminder block.** `<final_reminders>` MUST exist and MUST repeat the highest-priority rules. Format each line with a priority prefix:
   ```
   P0 — <hard rule, never violate>
   P1 — <strong rule, violate only with explicit justification>
   P2 — <preference / efficiency tip>
   ```
   **Group all P0 lines first, then all P1, then all P2.** Out-of-order priority lines confuse readers — the model scans top-to-bottom and assumes priority decreases monotonically. A P0 buried after P1s gets read as if it were lower priority.
6. **Positive instructions.** Tell the agent *what to do*, not just *what to avoid*. "Use LSP findReferences for callers" beats "do not Grep for callers" — though both together is fine.
7. **No implicit success.** If a skill writes code, runs tests, or modifies files, the success path MUST include a verification step (run the tests, read the diagnostic, etc.). "Claim tests passed without running them" is forbidden by global CLAUDE.md and must be re-stated in `<final_reminders>` for any skill that touches tests.
8. **Tool bans live in agent frontmatter, not in prompt rules.** If a skill must prevent the agent from using a specific tool (e.g. `Bash`, `Read` on source, `Edit`), the enforcement MUST be done by defining a custom subagent at `~/.claude/agents/<name>.md` with a `tools:` allowlist (or `disallowedTools:` denylist) that **physically removes the tool from the agent's inventory**. Prompt-level rules like "P0 — never use Bash" are soft constraints that the model routinely violates under pressure — proven empirically in this project. The pattern: define the agent file → dispatch via `Agent(subagent_type: "<custom-name>", ...)` from the skill. This is the **#1 enforcement mechanism** — reach for it before reaching for more prompt rules.

---

## P1 — Strong Recommendations

9. **Evidence before answer.** For research / exploration / review skills, the agent should first surface the relevant snippets (with `file:line`) and *then* draw conclusions. This filters noise and pulls the truly relevant context to the front of working memory.
10. **Few-shot examples.** Anthropic's guidance: 3–5 high-quality examples is the most reliable steering. For skills with non-obvious classification or output shape, include at least 2 positive examples and 1 anti-pattern example.
11. **Chaining for complex tasks.** If the skill is non-trivial, structure it as `draft → self-check → refine` (or `explore → plan → execute → verify`). Do not try to do everything in one pass.
12. **Self-check slot.** For skills that produce artifacts (code, tests, plans, summaries), include a self-check step against the `<success_criteria>` before returning.
13. **Subagent vs. main session boundary.** Every skill must be explicit about *where* it runs:
    - If it dispatches a subagent: name it (`name: "..."`), pass a complete self-contained prompt, and document how follow-ups are handled (`SendMessage` vs new agent).
    - If it runs in the main session: say so in `<role>` and explain why (e.g., needs user-in-the-loop STOP points).
    - Never leave this ambiguous.

---

## P2 — Stylistic Preferences

14. **Frontmatter description is a trigger, not a tagline.** It should let *future-Claude* decide in one read whether the skill applies. Lead with the trigger condition ("Use when...", "MUST invoke for..."), not marketing prose.
15. **One concrete action per instruction step.** If a step contains "and" or "or", you **MUST split it** into separate sub-steps with explicit branching (e.g. `Default: ... / Fallback: ...`, or numbered `2a` / `2b`). "Consider splitting" is too soft a rule — the model will rationalize past a soft rule under pressure. Either split, or accept that the step is ambiguous.
16. **`{{PLACEHOLDER}}` syntax** for substitutions inside embedded prompts. Make placeholders shout so they are not missed.
17. **Cross-skill references use absolute paths.** `~/.claude/skills/foo/bar.md`, not `../foo/bar.md`.
18. **Extended thinking hint.** For genuinely complex multi-step skills, a single `think thoroughly before your first action` line in `<instructions>` is usually more effective than over-prescribing the reasoning steps. **Threshold: at most one such hint per skill, and only for skills with 5+ instruction steps and non-obvious reasoning paths.** Do not sprinkle it on simple skills — it dilutes the signal everywhere.

---

## Reference template

```markdown
---
name: <skill-name>
description: <Use when ... / MUST invoke for ... — one-sentence trigger>
---

<role>
You are <who>, executing <where: main session | named subagent>. <One sentence about your core responsibility.> You never <one or two things this skill must NOT do, e.g. "read source files yourself" or "skip the user STOP points">.
</role>

<context>
<!-- Long reference material: tool docs, rules, playbooks. -->
</context>

<instructions>
1. <one concrete action>
2. <next concrete action>
...
</instructions>

<input>
- {{VAR_1}}: <what the caller passes>
- {{VAR_2}}: ...
</input>

<examples>
<example>
INPUT: ...
ACTIONS: ...
OUTPUT: ...
</example>

<example label="BAD — do not do this">
ANTI-PATTERN: ...
</example>
</examples>

<output_format>
<slot1>: ...
<slot2>: ...
</output_format>

<success_criteria>
The task is complete when ALL of these hold:
- ...
- ...
Stop the moment those hold.
</success_criteria>

<final_reminders>
P0 — <hardest rule>
P0 — <next hardest>
P1 — <strong recommendation>
P2 — <preference>
</final_reminders>
```

---

## Conformance check (mandatory before committing a skill edit)

**If you are an AI agent editing a skill file, you MUST mentally execute this checklist before declaring the edit complete.** Tick every box; if any box cannot be ticked, the skill is non-conforming and the edit must be revised before commit.

- [ ] Frontmatter `description` starts with a trigger phrase.
- [ ] `<role>` exists, names the execution location (main session vs subagent), AND lists at least one explicit "must NOT do" item (per the expanded rule #2).
- [ ] `<instructions>` are numbered and atomic (no "and"/"or" branches inside a single step — split per rule #15).
- [ ] `<output_format>` slots are concrete (no "summarize the result").
- [ ] `<success_criteria>` includes a stop rule.
- [ ] `<final_reminders>` exists with at least one P0 line, **and lines are grouped strictly P0 → P1 → P2** (no P0 buried after P1s).
- [ ] Long reference material is in `<context>`, not buried mid-instructions.
- [ ] Subagent-vs-main-session boundary is explicit.
- [ ] If the skill writes code, runs tests, or modifies files (per rule #7): a verification step is mandatory in the success path.
- [ ] All cross-skill / cross-file references use absolute paths.

If any box is unchecked, the skill is non-conforming. Fix before commit.
