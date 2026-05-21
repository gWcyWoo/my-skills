---
name: c-0
description: Implement in main session. Require user review and comply self-check before verification.
---

<role>Main-session implementer. Invoke `comply`. Pause for user review before verification.</role>


<instructions>
1. **Resolve files in scope.** Use files the caller explicitly named, or files named in the prior phase's requirement summary. If neither names any file, STOP and ask: *"Which files should I touch?"* Do NOT guess. Do NOT scan the repo.
2. **Explore code.** When you need to read or query source code, follow the active `AGENTS.md` source-exploration rules. Raw shell source reads and `rg` over source are forbidden.
3. **Implement the change.** Touch only the resolved files. Use `apply_patch` for existing files. Create a file only when its path is absent. If the caller passed red test files, implement only behavior asserted by those tests. NEVER modify the tests.
4. **Pause for review.** Ask: *"Implementation complete. Would you like to review before I run comply and lint/tests?"*
   - **Yes** → wait for feedback, apply changes, return to step 3.
   - **No / skip** → proceed to step 5.
5. **Gate check.** Ask yourself: *"Have I run comply on the diff yet?"* If no → step 6. If yes → return control to the caller.
6. **Load coding standards from diff.** Run `git diff` on the changed files, then invoke the `comply` skill, passing the diff and the file list.
7. **Self-check against comply rules.** Re-read the rules `comply` returned. Fix any violations. Then return control to the caller.
</instructions>

<output_format>
Return to the caller with:

Status:        ready-for-verify | blocked
Files touched: path:line per edited file, one-line description each
Rules applied: which rule sections from comply were enforced
Review:        accepted | accepted-after-changes | (not requested)
</output_format>

<final_reminders>
P0 — Source exploration follows the active `AGENTS.md` source-exploration rules. Raw shell source reads and `rg` over source are forbidden.
P0 — Step 5 gate check is mandatory. You CANNOT return to caller without running comply.
P0 — ALWAYS pause at step 4 for user review. Even if the change is one line.
P0 — NEVER expand scope unilaterally. If the change needs to grow, STOP and ask.
P0 — NEVER claim the implementation is verified — verification is the caller's Step 4. This skill only ends at "ready-for-verify".
P0 — If the caller passed red test files, your goal in step 3 is to make them green by writing implementation. If any red test passes before implementation, return `Status: blocked` and name the passing test. Do NOT weaken, skip, or modify the test.
P1 — Use `apply_patch` for existing files. Create a file only when its path is absent. Never overwrite an existing file wholesale.
P1 — Do not add error handling, validation, or fallbacks for scenarios the requirement did not name. Trust framework guarantees.
P1 — Do not add comments or docstrings to code you did not change.
</final_reminders>
