---
name: code-0
description: Use as the implementation step of any workflow in Codex — loads project coding standards via `comply`, implements the change in the MAIN session, and gates on user review before lint/test. The `-0` suffix denotes main-session execution (parallels `my-explore-0`).
---

<role>Implementation coordinator executing in the main session: delegates rule loading to the `comply` workflow and pauses for user review before completion.</role>

<instructions>
1. **Resolve files in scope.** Use files the caller explicitly named, or files named in the prior phase's requirement summary. If neither names any file, STOP and ask: *"Which files should I touch?"* Do NOT guess. Do NOT scan the repo.
2. **Load coding standards.** Invoke the `comply` skill, passing the task context and the resolved file list.
3. **Implement the change.** Apply the rules `comply` returned. Touch only the resolved files. Use `apply_patch` for existing files; create genuinely new files in the smallest reasonable way for the task. If the caller passed red test files from `write-tests`, write the minimum implementation that turns them green. NEVER modify the tests.
4. **Self-check.** Re-read the rules `comply` returned. Fix any violations before step 5.
5. **Pause for review.** Ask: *"Implementation complete. Would you like to review before running lint and tests?"*
   - **Yes** → wait for feedback, apply changes, return to step 4.
   - **No** → return control to the caller.
</instructions>

<output_format>
Return to the caller with:

Status:        ready-for-verify | blocked
Files touched: path:line per edited file, one-line description each
Rules applied: which rule sections from comply were enforced
Review:        accepted | accepted-after-changes | (not requested)
</output_format>

<final_reminders>
P0 — ALWAYS invoke `comply` first. Never read rule files directly in the main session.
P0 — ALWAYS pause at the review STOP. Even if the change is one line.
P0 — NEVER expand scope unilaterally. If the change needs to grow, STOP and ask.
P0 — NEVER claim the implementation is verified. Verification is the caller's Step 4. This skill only ends at `ready-for-verify`.
P0 — If the caller passed red test files, your goal in step 2 is to make them green by writing implementation. If any of them pass before you write any implementation, the test is wrong; surface that to the user immediately and do not weaken the test, skip it, or modify it to pass.
P1 — Use `apply_patch` for manual edits. Never overwrite an existing file wholesale.
P1 — Do not add error handling, validation, or fallbacks for scenarios the requirement did not name. Trust framework guarantees where appropriate.
P1 — Do not add comments or docstrings to code you did not change.
</final_reminders>
