---
name: c3
description: Negotiate a solution with Codex via ./c3/{date}/{session}/conversations.md. Event-driven: a background `wait_for_turn.py` blocks on fsevent until the pending inbound batch arrives; `append_turn.py --message-file` writes outbound; the transcript is the synchronization source of truth. Invoke as `/c3 <session-name>` (no `/loop` wrapper, no ScheduleWakeup — re-arm cycle is driven by harness `<task-notification>` on background subprocess exit).
---

<role>
Claude side of c3. Initial tick: resolve `$base`/`$dialog`, write `target.md` + initial `To codex:` turn if initiating, arm background `wait_for_turn.py "$dialog" claude`. Each subsequent tick fires from the harness's `<task-notification>` when the background watcher exits with the pending inbound batch on stdout: process the entire batch, write ONE outbound via `Write` + `append_turn.py --message-file`, re-arm the background watcher. The user is an OBSERVER; substance flows through `$dialog` and `notes-{ts}.md`. The transcript is the sync source — no side-channel state changes (per I1).
</role>

<context>
**Files** under `{base}` = `<project>/c3/{YYYY-MM-DD}/{session}/`:
- `target.md` — problem to solve (initiator writes once)
- `conversations.md` — canonical dialogue log (no `conversation.md` fallback)
- `solutions.md` — agreed solution
- `notes-{ts}.md` — `u-0` evidence dumps cited from conversation

**Wire format** for `$dialog`:
```
- 2026-04-27 14:30:05 To Codex:
  - <content>
  - done
```
Header: `- {ts} To {Codex|Claude|User}:`. Standalone `- done` is the only completion signal. Header timestamps are advisory (per I6 — clock skew is real); APPEND ORDER is canonical for sequencing.

**I/O scripts** (Claude-side, self-contained at `~/.claude/skills/c3/scripts/` — Codex maintains his own copy at `~/.agents/skills/c3/scripts/`; neither side modifies the other's):
- read: `python3 ~/.claude/skills/c3/scripts/wait_for_turn.py "$dialog" claude` — blocks on fsevent (`watchdog`) with polling fallback (`--poll-seconds`, default 60s safety net). Returns ALL pending inbound turns (the batch per I3) on stdout, exit 0. **Always invoke with `run_in_background=true`** — harness sends `<task-notification>` on subprocess exit, delivering stdout to the next tick.
- write: (1) `Write` block body to `/tmp/c3_block_{ts}.txt` (bullet content only, no header/done framing); (2) `python3 ~/.claude/skills/c3/scripts/append_turn.py "$dialog" codex --message-file /tmp/c3_block_{ts}.txt`. The script auto-formats header (`- {ts} To codex:`) + indented bullets + `- done`.

**`solutions.md` template:**
```markdown
# {session} — Agreed Solution
## Problem
<restatement of target.md>
## Solution
<numbered steps; each names file:line + the edit>
## Test Plan
<commands the reviewer will run>
## Acceptance Criteria
<bullets — what the reviewer checks>
```
</context>

<instructions>
0. **Pre-flight: resolve `$base` and `$dialog`.** `default_base = ./c3/$(date +%Y-%m-%d)/{{SESSION_NAME}}/`. If exists → `base = $default_base`. Else `find . -maxdepth 6 -type d -path "*/c3/$(date +%Y-%m-%d)/{{SESSION_NAME}}"`. Else if no `target.md` → initiating: `AskUserQuestion` for target body, `mkdir -p`, `Write target.md`. Else mid-session → `AskUserQuestion` for absolute project path. `$dialog = ${base}conversations.md`.

1. **Initiating** (no `$dialog` on disk): invoke the `u-0` skill via the **Skill tool** (`Skill(skill="u-0", ...)`) on `target.md` — `u-0` is a MAIN-session skill, **not an Agent subagent_type**, do NOT call `Agent(subagent_type="u-0")` (will error with "Agent type not found"). Then `Write` `${base}notes-{ts}.md` with findings → write initial `To codex:` block via the write helper (target understanding + proposed direction, citing `file:line`) → arm background watcher → tick line.

2. **On `<task-notification>` from background `wait_for_turn`**: stdout contains the pending inbound batch (one or more `To claude:` turns in append order). Process the WHOLE batch (per I3) before appending exactly ONE outbound — that single response answers the entire batch.

3. **Route by batch content** (first match across batch wins):
   - **approves implementation** ("approved", "LGTM against solutions.md") → write `To codex: implementation approved; sealing` → tick line `loop ended (approved)`. DO NOT re-arm.
   - **flags review issues** → fix in-scope (out-of-scope: write `To codex: issue K out of scope: {reason}`); re-run tests + lint + type-check (self-fix ≤3); on green write `To codex: revisions applied; tests/lint/typecheck passed; please re-review`; re-arm.
   - **announces peer wrote `solutions.md`** → `Read` `${base}solutions.md`, verify against `target.md`. If sound → write `To codex: solutions.md confirmed; awaiting user gate (per I4)` → **HALT** (do NOT re-arm; tick line announces gate). Else → write `To codex: solutions.md needs revision: 1. … 2. …`; re-arm.
   - **confirms our `solutions.md`** ("confirmed", "go implement") → write `To codex: confirmed; awaiting user gate (per I4)` → **HALT**.
   - **assigns Claude as `solutions.md` writer** ("+1 you write solutions.md") → `Write` `${base}solutions.md` per template → write `To codex: solutions.md ready, please review` → re-arm. Do NOT implement.
   - **else (normal discussion)** — physical action sequence: (a) for requirement understanding invoke `u-0` via the **Skill tool** (`Skill(skill="u-0")` — NEVER `Agent(subagent_type="u-0")`, no agent type by that name exists); for raw code exploration dispatch the `my-explore` subagent via `Agent(subagent_type="my-explore", prompt=<request per ~/.claude/agents/my-explore/PROTOCOL.md>)` on the message + referenced code; (b) `Write` `${base}notes-{ts}.md` with full evidence (file:line citations, verdicts, mechanism); (c) write `To codex:` block (file:line-citing bullets); (d) re-arm.

4. **Implement** (entered ONLY after user passes I4 gate; ownership per I5): apply each Solution step in `solutions.md` (dispatch the `my-explore` subagent via `Agent(subagent_type="my-explore", prompt=<request per ~/.claude/agents/my-explore/PROTOCOL.md>)` if files differ from the spec; STOP on non-trivial gaps). Run tests + lint + type-check. Self-fix ≤3; persistent failure → write `To user: implementation blocked: {check}: {error}; what I tried: …` → HALT. On green: write `To codex: implementation done; changed: {file:line list}; tests/lint/typecheck passed; please review` → re-arm.

5. **Re-arming the watcher**: after any non-HALT outbound write, invoke `python3 ~/.claude/skills/c3/scripts/wait_for_turn.py "$dialog" claude` with `run_in_background=true`. The harness `<task-notification>` on subprocess exit drives the next tick.
</instructions>

<input>
- {{SESSION_NAME}}: directory name under `./c3/{date}/`. Single token.
</input>

<output_format>
EXACTLY ONE LINE per tick to the user:
- `[c3:{session}] {action}` — normal ticks (e.g., `armed watcher`, `processed batch of N, replied`).
- `[c3:{session}] HALTED — awaiting user gate (per I4)` — paused for user `solutions.md` confirmation + ownership.
- `[c3:{session}] HALTED — implementation blocked` — paused for user intervention on persistent test/lint/typecheck failure.
- `[c3:{session}] loop ended ({approved|blocked})` — terminal.

No multi-line summary, no per-claim list, no closing recap. All substance lives in `$dialog` and `notes-{ts}.md` — the user reads those for detail.
</output_format>

<final_reminders>
P0 (I1) — Transcript-first: every artifact write or state transition (target.md, solutions.md, notes-*.md, code edits, implementation start/end, review verdict, seal) MUST be immediately followed by a `To <other>` turn naming the artifact path and ending with `- done`. No side-channel state changes — the other side cannot see what isn't in the transcript.
P0 (I2) — Filesystem events are the wake mechanism only; `conversations.md` is the synchronization source. Artifact files (`solutions.md`, `notes-*.md`, code) do NOT replace transcript turns.
P0 (I3) — Batch processing: `wait_for_turn.py` returns ALL pending inbound turns (every complete `To claude:` after our last `To codex:` in append order). Process the WHOLE batch before appending ONE outbound — that single response answers the entire batch. Stateless: append-order only, no cursor, no turn IDs.
P0 (I4) — User confirmation gate: after `solutions.md` is agreed by both sides, HALT. Tick line surfaces the gate. Do NOT re-arm; do NOT implement until user explicitly confirms.
P0 (I5) — Ownership at gate: user picks (a) Claude implements + Codex reviews [DEFAULT if user says only "confirm"/"go"] / (b) Codex implements + Claude reviews / (c) cross-write / (d) user implements + both review. Cross-write requires explicit opt-in.
P0 (I6) — Append order > timestamps. Header timestamps are advisory only (clock skew between Claude/Codex is real — observed 6+ min in c3-v2 session). Reasoning about turn sequence MUST use file append order.
P0 — User is an OBSERVER, not a recipient. Never inline verification reports, per-claim verdict lists, fix proposal bodies, review summaries, or closing recaps in user-facing text. Substance flows through `$dialog` + `notes-{ts}.md`. User-facing output per tick is the single `<output_format>` line.
P0 — Every code claim cites `file:line` from `notes-{ts}.md`. Memory is not evidence.
P0 — `u-0`, `c-0`, `um0` are SKILLS, not Agents. Invoke via `Skill(skill="u-0")` etc. — NEVER `Agent(subagent_type="u-0")`. The `-0` suffix denotes MAIN-session skill execution; no agent type by that name exists. `my-explore` IS an agent — dispatch via `Agent(subagent_type="my-explore", ...)`; do NOT call `Skill(skill="my-explore-0")` (that skill is now the subagent's tool-palette reference, not a user-facing entry).
P0 — Implementation edits stay in `solutions.md` scope; out-of-scope changes need user OK. Pre-review gate: tests + lint + type-check actually pass before posting `please review`. Self-fix ≤3; else `To user: implementation blocked: …`.
</final_reminders>
