# ICP visual verification contract v1

This contract is the public visual-acceptance interface for one ICP page node.
The page worker owns every capture and repair iteration. ICP validates only its
terminal evidence. IOLE never receives or reacts to an intermediate mismatch.

## Observable contract before edits

Before production edits, enumerate every required visual state from the exact
design reference and the approved Sheet UT/IT/E2E contract. Give each state one
plain-language observable contract. Identify the page/component public target and
the node's `allowed_paths` ownership boundary. If the required states, target, or
design are incomplete or contradictory, return a controlled failure without
guessing.

For every state, declare:

- at least one geometry anchor with expected coordinate, actual coordinate, and
  tolerance;
- at least one named visual region with measured and maximum mismatch ratios;
- the exact user action or deterministic setup that reaches the state.

## Deterministic capture calibration

Before the baseline capture, fix reference/runtime viewport size, density, font
scale, locale, theme, system-bar policy, and disabled animations. Reference and
runtime pixel dimensions must match. A calibration problem is classified as
`capture-normalization`; do not compensate for it by changing production layout.

Every real final-capture provenance document extends
`icp.runtime-provenance.v1` with non-empty `capture_id` and `state_reset_id`.
The two final runs require distinct capture and reset identifiers. Their image
bytes may be identical; stable identical pixels are valid after two independent
capture/reset events.

## Measured root-cause loop

The first normalized comparison is iteration 0, not a terminal failure. When a
material metric fails:

1. Classify exactly one root cause as `capture-normalization`, `layout`,
   `typography`, `color`, `asset`, or `state`.
2. Select one named target and record its normalized `[0,1]` `before_score`
   (lower is better) from the same deterministic metric used after repair.
3. Apply the minimum production change for that root cause only.
4. Reset the state, recapture it, and record `after_score` from the same metric.
5. Continue while the score improves. Refactor only while behavior and visual
   acceptance remain green.

Do not publish a worker result after the first mismatch. Return `status=failed`
only when design/runtime access is unavailable, the approved observable contract
is incomplete or contradictory, or the same state/classification/target has two
consecutive targeted repairs with no measurable improvement. Preserve all RED,
GREEN, and explicitly untested-boundary evidence in the node state.

## Passing evidence

After all declared states are green, reset and capture every state twice. Seal
each run with `shared_core/visual_evidence_v1.py`, then build
`visual-verification.json` with
`shared_core/visual_verification_v1.py`. A passing
`icp.visual-verification.v1` contains exact calibration, state contracts, anchors,
regional metrics, repair history, and exactly two passed final manifests per
state. ICP rejects a missing/tampered bundle, failed anchor or region, reused
capture/reset provenance, wrong platform capture source, or any artifact outside
the node state.
