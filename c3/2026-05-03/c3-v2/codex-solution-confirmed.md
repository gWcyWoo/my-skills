solutions.md confirmed; awaiting user gate.

I reviewed the latest `solutions.md` against `target.md`, the user's protocol correction, and the live failures in this transcript.

Confirmed:
- I1 transcript-first invariant covers artifact/state side-channel failures.
- I2 correctly makes filesystem events the wake mechanism while keeping `conversations.md` as the synchronization source.
- I3 batch-processing now fixes dropped inbound turns without hidden cursor state, turn IDs, timestamp ordering, or contradictory per-turn ack semantics.
- I4 correctly halts after `solutions.md` agreement for user confirmation.
- I5 correctly makes ownership user-assigned at the gate, with default Claude implements and Codex reviews when unspecified.
- I6 correctly makes append order canonical over timestamps.
- Technical steps and Test #8 now match the agreed protocol.

On `render_turns`: use one blank line between rendered turn blocks. That matches the transcript's existing visual separator and keeps batch output readable while preserving each complete turn's header/body/done framing.

Do not implement yet. Per I4, the protocol now halts for user confirmation and ownership assignment.
