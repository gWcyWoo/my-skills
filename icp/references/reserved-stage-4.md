# Reserved Stage 4 — independent delivery acceptance and learning

## Status

This stage is recorded for future design but is not active. ICP is complete when
Stage 3 implementation verification exits zero. Do not create a Stage-4 project
directory, artifact, command, or gate until the user explicitly activates this
stage and approves its final contract.

The former visual-fidelity acceptance work is already part of Stage 3. Stage 4
must not repeat reference-viewport checks, responsive checks, interaction tests,
or code-coverage verification merely to create another completion boundary.

## Intended outcome if activated

Independently assess the already verified implementation as a delivery candidate
and turn delivery observations into auditable feedback without generating or
repairing production code inside this stage.

Its proposed responsibilities are:

1. Consume the immutable Stage-3 result, implementation manifest, runtime
   evidence, visual-difference report, and packaged application artifact.
2. Confirm that the reviewed delivery candidate is the exact artifact proved by
   Stage 3 rather than a later or different build.
3. Perform independent delivery-environment observation, such as supported real
   devices or release-like packaging, without replacing Stage-3 deterministic
   checks or introducing screenshot-specific thresholds.
4. Produce one concise delivery-acceptance report containing accepted evidence,
   observed issues, and exact ownership routing. A code defect returns to Stage 3;
   a component-contract defect returns to Stage 2; a design-data or Block defect
   returns to Stage 1.
5. After acceptance, propose reusable project lessons for the project's own
   guidance file. Do not silently change project guidance from observations.

## Boundary

Stage 4 does not generate code, repair code, reinterpret designs, change component
boundaries, commit, push, create an MR, or update Sheet status. IOLE remains the
owner of delivery mode and `review` writeback. Until Stage 4 is explicitly
activated, no current ICP run reads this reference as an execution instruction.
