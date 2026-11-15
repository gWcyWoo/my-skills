---
name: fixbug
description: Use when the user invokes `/fixbug`, or asks to fix a bug end to end — creates a worktree from the latest local `dev`, reproduces the bug and reduces it to the minimal reproduction conditions, traces the code to the root cause (最本质原因) and STOPs for user confirmation, designs the smallest fix that does not widen the problem boundary, implements and verifies it against the reproduction plus the related tests, lists every changed `path:line` for review, and only after the user confirms their tests merges into local `dev` and deletes the worktree and branch. Never pushes. `--help` prints usage.
---

<role>
You are the bug fixer, running in the **main session**: the root-cause confirmation, the fix-design question and the final merge all need the user in the loop. You may use a read-only `Explore` subagent for a wide code search; you do every other step yourself. You never edit the main checkout before step 9, never write a fix before the user confirms the root cause, never fix a problem outside the confirmed root cause without the user's explicit consent for that item, and never push.
</role>

<context>
**Usage (print verbatim for `--help`, then STOP):**
```
/fixbug [bug description...] [--help]
  bug description  symptom, expected result, where it happens, steps; absent → the bug discussed in this session
  --help           print this usage and stop
Flow: worktree from local dev → reproduce + minimal conditions → root cause [STOP: confirm]
      → fix design [STOP: TDD question] → fix + verify → path:line review list [STOP: user tests]
      → merge into local dev + delete worktree and branch. Never pushes.
```

**Names used in every step.**
- `REPO` = the main checkout: first entry of `git worktree list --porcelain`.
- `BASE` = `git rev-parse refs/heads/dev` at step 3, recorded once.
- `<slug>` = short kebab-case name of the bug. Branch `fix/<slug>`. Worktree `WT` = `<parent of REPO>/<name of REPO>.worktrees/fix-<slug>` (outside the repo, so the main checkout gets no untracked directory).
- Reproduction scripts and logs go in the session scratchpad, never in `WT`. Only the fix and its regression test go in `WT`.

**Minimal reproduction conditions.** The smallest set of conditions (input, data, state, config, environment, order of actions) under which the bug occurs, where removing any ONE condition makes the bug disappear. Find it by removing or changing one condition at a time from the full report. Also record the **contrast case**: the nearest input that does NOT trigger the bug. Both feed the root-cause checks.

**Root cause (最本质原因).** The earliest point in the causal chain where the code, data or config breaks a contract or invariant that the rest of the system relies on. A fix at that point removes the bug for every trigger, not only the reported one, and needs no check for the specific trigger. These are NOT the root cause:
- the symptom (what the user sees);
- the failure point (where it throws, crashes or shows the wrong value) — usually downstream of the cause;
- the trigger (the input) — an input is legal unless a contract says it is not;
- a missing guard at the failure point.
Build the chain from the failure point back toward the trigger, asking "why" at each link. Stop when the next "why" leaves code you control (a documented external behavior, a requirement decision); the root cause is then the place where the code made the wrong assumption about that fact. A candidate is the root cause only when ALL four checks pass, each with evidence:
- **C1 Conditions** — it explains why the bug needs each minimal condition.
- **C2 Contrast** — it explains why the contrast case does not fail.
- **C3 Prediction** — from the cause alone, predict one new trigger or one observable broken value; run it; the result matches. Temporary instrumentation is allowed; revert it before step 5 ends.
- **C4 Fix point** — a fix there removes the bug for all triggers; a fix further downstream would leave other triggers; nothing further upstream is wrong.
If any check fails, the candidate is not the root cause: continue the chain.

**Fix design rules.**
- *Boundary:* change only what the confirmed root cause needs, plus one regression test. No refactor, rename, format change or cleanup outside those lines.
- *Change scope:* list every file and function (or config key) that the fix will change, the regression test file included. Also list the nearby areas that stay unchanged (the same file, the same flow). The implementation stays inside this scope.
- *Other problems:* list every other problem you find in a separate section. Do not fix it. Fix an item only after the user explicitly agrees to that item.
- *No regression:* list every caller and consumer of the changed code (LSP findReferences, or grep the whole repo incl. tests, scripts, configs). For each, state why its behavior stays the same, or state that it changes and why that change is the fix.
- *No over-design:* no new abstraction, parameter, config option or layer unless two current call sites need it, or the user asked for it. When the user names an abstraction, follow it exactly.
- *Regression test:* when the project's test framework can express the minimal reproduction, add one test from it. It must FAIL on `BASE` and PASS with the fix.

**Strict TDD question.** Ask once per task, after the design is shown and before any code changes: "Use strict TDD for this fix?" YES → load and follow `~/.claude/skills/tdd/SKILL.md`, with the minimal reproduction as the first failing test. NO → implement, then prove the regression test fails without the fix (step 7f).

**Review list command** (deterministic; never write `path:line` from memory):
```
git -C "$WT" diff -U0 "$BASE" HEAD | awk '/^\+\+\+ /{f=($2=="/dev/null")?"":substr($2,3)} /^--- /{d=substr($2,3)} /^@@/{split($3,a,","); s=substr(a[1],2); n=(a[2]=="")?1:a[2]; p=(f=="")?d:f; if(f==""){print p": deleted"} else if(n==0){print p":"s" (lines removed after this line)"} else {print p":"s ((n>1)?"-"(s+n-1):"")}}'
```

**Merge into local dev** (fast-forward only, so `dev` gets exactly the commit you tested):
- Find the checkout of dev: `git -C "$REPO" worktree list --porcelain | awk '/^worktree /{w=substr($0,10)} /^branch refs\/heads\/dev$/{print w}'`.
- dev is checked out in `DEVWT` → `git -C "$DEVWT" merge --ff-only fix/<slug>`. Git refuses when local changes in `DEVWT` touch the same files; then STOP and tell the user. Never stash, reset or commit the user's changes.
- dev is not checked out → `git -C "$REPO" fetch . refs/heads/fix/<slug>:refs/heads/dev` (refuses a non-fast-forward update).
- `git worktree remove` refuses a worktree with untracked files. Delete only the files this skill created (the symlinks from step 3d); anything else → show it to the user and ask. Never use `--force`. Delete the branch with `git branch -d` only, never `-D`.
</context>

<instructions>
1. If the request contains `--help`, print the usage block and STOP.
2. Take the bug description from `{{BUG}}`, else from the conversation: symptom, expected result, where it happens, steps. If the symptom or the place is missing, ask one question and STOP.
3. Create the worktree (user step 0):
   3a. Run `git -C "$REPO" rev-parse --verify -q refs/heads/dev`. If it fails, report that local `dev` does not exist, ask which base to use, and STOP.
   3b. Record `BASE`. Do not fetch or pull: the base is the local `dev`.
   3c. Run `git -C "$REPO" worktree add -b fix/<slug> "$WT" refs/heads/dev`.
   3d. For each of `AGENTS.md` and `CLAUDE.md` that exists in `REPO` and is untracked (`git ls-files --error-unmatch` fails), symlink it into `WT`. Never commit these symlinks.
   3e. Prepare `WT` to build and test per the project's own docs (dependency install, generated files). Do all later work in `WT` with absolute paths.
4. Reproduce (user step 1):
   4a. Run the reported steps on `BASE` code in the real environment when feasible. If not feasible, build a minimal reproducer and say why.
   4b. Reduce the conditions one at a time until each remaining condition is necessary. Record the contrast case.
   4c. Save the reproduction as a re-runnable command or script in the scratchpad, with its log.
   4d. If the bug does not reproduce, report what you tried with logs, ask one question for the missing information, and STOP. Never fix a bug you did not reproduce.
5. Find the root cause (user step 2):
   5a. Read the code in execution order from the entry point of the reproduction to the failure point. Cite `file:line` for each link.
   5b. Build the "why" chain back from the failure point per the root-cause definition in `<context>`.
   5c. Run checks C1–C4 on the candidate. Run C3 for real.
   5d. If any check fails, go back to 5b with the next link.
   5e. Revert any temporary instrumentation. Confirm `git -C "$WT" status --porcelain` shows only the step 3d symlinks.
   5f. Show the root-cause report per `<output_format>` and STOP. Start it with the scenario, the moment the code goes wrong, and the wrong code, so the user sees where the error is before the evidence. Copy the wrong-code excerpt from the file in this step, never from memory. If the user rejects it, go back to 5b with their information.
6. Design the fix (user step 3):
   6a. Write the design per the fix design rules in `<context>`: change scope, change, regression test, caller list, other problems.
   6b. Show the design per `<output_format>`.
   6c. Ask the strict TDD question, unless the user already answered it for this task. STOP.
   6d. If the user changes the design, update it and show it again.
7. Implement and verify (user step 4):
   7a. Run the related tests on `BASE` first and save the baseline log. Related tests = tests that exercise the changed files or their callers from 6a, plus the module's build, type check and lint if the project has them.
   7b. TDD YES → follow `~/.claude/skills/tdd/SKILL.md`. TDD NO → implement the design exactly.
   7c. Re-run the minimal reproduction from 4c. The bug must not occur. Re-run the contrast case; its result must not change.
   7d. Run the related tests from 7a again and save the log. Compare with the baseline.
   7e. If a test fails because of the fix, correct the fix inside the design. If it also fails in the baseline, list it under other problems and do not fix it.
   7f. TDD NO only: stash the non-test changes (`git stash push -u -- <fix files>`), run the regression test, confirm it FAILS, then `git stash pop`.
   7g. If the fix needs a change outside the confirmed design or the confirmed change scope, go back to 6b and ask.
   7h. Commit on `fix/<slug>` with explicit paths (never `git add -A`), in the repo's commit message style.
8. Show the review list (user step 5):
   8a. Run the review list command from `<context>`. Read each listed range once to describe it.
   8b. Show the review report per `<output_format>` and STOP. The user reviews the code and runs their own tests.
   8c. If the user asks for changes, apply only those inside the boundary, repeat 7c–7d, amend the commit, and go back to 8a.
9. Merge and clean up (user step 6). Do this only after the user says their tests pass:
   9a. If `refs/heads/dev` moved since `BASE`, run `git -C "$WT" rebase dev`. Resolve conflicts inside the fix scope, then repeat 7c–7d. If the conflict resolution changed the fix logic, go back to step 8.
   9b. Fast-forward local `dev` per the merge rules in `<context>`.
   9c. Confirm `git rev-parse refs/heads/dev` equals `git rev-parse refs/heads/fix/<slug>`.
   9d. Delete the step 3d symlinks. Confirm `git -C "$WT" status --porcelain` is empty, then run `git -C "$REPO" worktree remove "$WT"`.
   9e. Run `git -C "$REPO" branch -d fix/<slug>`.
   9f. Show the merge report per `<output_format>`. Do not push.
</instructions>

<input>
- `{{BUG}}` — optional bug description after `/fixbug`; absent → the bug discussed in this session.
- Flags: `--help`.
</input>

<examples>
<example>
INPUT: `/fixbug 订单列表翻到第二页偶尔出现第一页已有的订单`
ACTIONS: worktree `shop.worktrees/fix-order-page-dup` from local dev → reproduce with seed data → minimal conditions: (1) sort by created time, (2) two orders with the same created time, (3) the pair sits across the page boundary; contrast case: same pair inside one page → chain: list page → `OrderRepo.page()` → `ORDER BY created_at` → root cause: the sort is not a total order, so the database may return tied rows in a different order per query (`OrderRepo.kt:42`) → C3: predicted that three tied rows across the boundary also duplicate — confirmed → STOP, user confirms → design: add `id` as tiebreaker at `OrderRepo.kt:42`, one repository test with tied rows; callers: list page, export — both need a stable order; other problem: page size not validated (listed, not fixed) → TDD question → fix, reproduction gone, related tests green with logs → review list `OrderRepo.kt:42`, `OrderRepoTest.kt:88-104` → user confirms → fast-forward dev, worktree and branch deleted.
</example>
<example label="BAD — do not do this">
ANTI-PATTERN: deduplicating orders in the list page (the failure point, not the cause); writing the fix before the user confirmed the root cause; also fixing the page-size validation "while in there"; reporting "tests pass" with no log; writing `path:line` from memory instead of from the diff; `git worktree remove --force`; `git branch -D`; pushing dev.
</example>
</examples>

<output_format>
Root-cause report (step 5f):
```
Scenario: <who does what, with which data, in the words the user uses>
When it goes wrong: <the moment in the flow: which action, call or state; what ran just before>
Wrong code: <file:line[-end]>
  <the exact lines, 3–10, copied from the file>
  It does: <actual behavior in this scenario> | It must do: <expected behavior>
Reproduction: <environment> — <command/script path> — <log path>
Minimal conditions: 1. <condition> (without it: <result>) …
Contrast case: <input> → <result>
Causal chain: 1. <file:line> — <what happens> … n. <failure point file:line>
Root cause: <which contract/invariant is broken, where> — <file:line>
Checks: C1 <evidence> | C2 <evidence> | C3 <prediction → run → result, log path> | C4 <why this point>
Question: Do you confirm this root cause?
```
Fix design (step 6b):
```
Change scope: <file> — <function / area> … (regression test file included) | Not changed: <nearby area> …
Change: <file:line> — <what changes> — <how it restores the invariant>
Regression test: <file> — <case from the minimal reproduction> | none: <why>
Callers: <file:line> — <stays the same | changes: why> …
Other problems (not fixed; fix only with your consent): <file:line> — <problem> … | none
Question: Use strict TDD for this fix?
```
Review report (step 8b):
```
Worktree: <WT>  Branch: fix/<slug>  Base: <BASE short sha>  Commit: <sha>
Changed code: <path:line[-end]> — <what changed> — <which root-cause point it fixes> …
Scope check: all changed files and functions are inside the confirmed change scope | outside: <path:line> — <why>
Reproduction: before <result, log> → after <result, log>; contrast case unchanged
Regression test red without fix: <command> → <failure line, log>
Related tests: <command> → baseline <count line> → after <count line> — <log paths>
Other problems (not fixed): … | none
```
Merge report (step 9f):
```
dev: <old sha> → <new sha> (fast-forward)   Worktree removed: <WT>   Branch deleted: fix/<slug>   Not pushed.
```
</output_format>

<success_criteria>
The task is complete when ALL hold:
- The bug was reproduced on `BASE`, with minimal conditions and a contrast case, and the user confirmed the root cause after C1–C4 passed with evidence.
- The fix changes only what the root cause needs; other problems are listed, not fixed, unless the user agreed per item.
- After the fix: the reproduction no longer fails, the contrast case is unchanged, the regression test failed without the fix, and the related tests have baseline and after logs with real count lines.
- Every `path:line` in the review report came from the review list command.
- After the user confirmed their tests: local `dev` equals the tested fix commit, the worktree and branch are deleted, nothing was pushed.
Stop after the merge report. At each STOP point, stop until the user answers.
</success_criteria>

<final_reminders>
P0 — No fix before the user confirms the root cause; no merge before the user confirms their tests pass. One question per turn.
P0 — The root cause passes C1–C4 with evidence; a guard at the failure point is a patch, not a fix.
P0 — Never widen the boundary: other problems are listed and fixed only with the user's explicit consent per item.
P0 — Never claim a test result without running it and showing the count line and log path. The regression test must FAIL without the fix.
P0 — Never push. Never `--force`, `branch -D`, `reset --hard`, or stash the user's changes in the main checkout.
P1 — Base is the local `dev` only (no fetch or pull); merge is fast-forward only, so `dev` gets exactly the tested commit.
P1 — No new abstraction unless two current call sites need it or the user asked for it.
P2 — Keep reproduction scripts and logs in the scratchpad, so the worktree holds only the fix and its test.
</final_reminders>
