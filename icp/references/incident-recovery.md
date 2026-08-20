# Run-local incident recovery

Use this protocol only when an unexpected ICP/IOLE tooling or contract failure
prevents the normal stage state machine from continuing. It preserves delivery
progress without pretending to diagnose or repair the underlying Skill defect.

Do not use it for expected TDD RED, application compilation failures, a semantic
`revise`, missing user/source authority, or an ordinary failed gate that already
has an owning repair loop.

## 1. Freeze and record

Stop the failed command immediately. Do not delete or rewrite `.icp` evidence.
Save the exact argv as a JSON string array and the exact stderr/stdout failure in
temporary files, then run:

```bash
python3 <icp-skill>/scripts/incident_recovery.py record \
  --project-root <project> \
  --stage extract|component-design|implementation|orchestration \
  --failed-command <argv.json> \
  --exit-code <non-zero> \
  --error-output <failure.txt> \
  --last-checkpoint <project-relative-checkpoint> \
  --state-file <project-relative-state.json> \
  [--artifact <relevant-input-or-output> ...]
```

The command records the objective phenomenon, involved hashes, last checkpoint,
current state files, the complete frozen `.icp` baseline, and the workspace
outside `.icp`. `root_cause` is always JSON `null`.

## 2. Recovery subagent boundary

Give the subagent only the generated `incident.json`, the target project, and the
normal ICP instructions. Its task is operational recovery, not diagnosis.

It may:

- read the failed inputs, outputs, state, and frozen contracts;
- create a semantically equivalent input, compatibility projection, or other
  temporary data under `.icp/incidents/<incident-id>/recovery-data/`;
- run the narrow invariant checks needed to prove that the recovery preserves the
  authoritative source, hashes, component boundary, and business behavior;
- return one exact no-shell argv for the main session to resume.

It may not:

- modify ICP/IOLE Skills, scripts, prompts, or tests;
- diagnose or claim a root cause;
- modify production/test code, Sheet state, Git, branch, commit, push, or PR;
- edit, delete, rehash, or mark passing any frozen `.icp` artifact;
- weaken a gate or use a different business interpretation.

The safest recovery reuses an already-verified equivalent artifact. If new data
is unavoidable, preserve the original and write a derived copy only inside the
incident recovery-data directory.

## 3. Record the temporary recovery

Create an input with this exact shape:

```json
{
  "schema": "icp.incident.temporary-recovery.v1",
  "incident_id": "incident-...",
  "strategy": "What run-local data permits the original contract to continue.",
  "recovery_data_paths": [
    ".icp/incidents/incident-.../recovery-data/equivalent-input.json"
  ],
  "resume_command": ["python3", "...", "original-command", "..."],
  "invariant_checks": [
    {
      "name": "semantic identity preserved",
      "passed": true,
      "evidence": "Exact digest or contract evidence."
    }
  ],
  "limitations": ["The underlying ICP tooling defect remains unresolved."]
}
```

Then run:

```bash
python3 <icp-skill>/scripts/incident_recovery.py record-recovery \
  --project-root <project> \
  --incident-id <incident-id> \
  --recovery <temporary-recovery.json>
```

The command fails if any file outside `.icp` changed, any frozen `.icp` evidence
changed, recovery data escaped the incident directory, a file was undeclared, or
an invariant did not pass.

## 4. Resume and disclose

Return control to the main session. It rereads the current ICP Skill and the
recorded incident/recovery, then executes the exact returned resume argv from the
last successful checkpoint. Do not rerun completed stages solely because an
incident occurred.

Before the final response run:

```bash
python3 <icp-skill>/scripts/incident_recovery.py pending \
  --project-root <project>
```

Report every open or temporarily recovered incident with its ID, phenomenon,
temporary recovery, verification evidence, and the explicit reminder that the
underlying ICP defect still requires separate treatment.
