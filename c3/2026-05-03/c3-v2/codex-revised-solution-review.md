Changes requested.

The revised `solutions.md` correctly incorporates the user's protocol corrections on transcript-first synchronization, user confirmation gate, ownership selection, and append-order over timestamps. I support I1, I2, I4, I5, and I6.

Blocking issue: I3's proposed "oldest unanswered" semantics are not implementable as written with only the current transcript format.

Evidence from the revised `solutions.md`:
- I3 defines "unanswered" as: no `To <peer>` turn from the recipient appearing AFTER this inbound turn in append order.
- Test #8 writes two complete inbound `To claude` turns, then appends one outbound `To codex` reply after both. It expects the second `To claude` turn to remain unanswered.

Why this is wrong:
- Under I3's own definition, the outbound `To codex` reply appears after BOTH inbound `To claude` turns, so both inbound turns are answered.
- A stateless `wait_for_turn.py` reading only `conversations.md` cannot know that the reply was intended to answer only the first inbound turn.
- Therefore Test #8 contradicts I3's definition and would require hidden cursor state, explicit turn IDs/acks, or a rule that one outbound reply can only answer one inbound turn. None of those are in the agreed protocol.

Required fix:
Replace I3 with an implementable backlog rule:

I3 — No dropped inbound / batch processing invariant.
- `wait_for_turn.py` returns all complete inbound turns that appear after the last complete outbound turn by the recipient, in append order.
- If there is exactly one pending inbound turn, it prints that turn.
- If there are multiple pending inbound turns, it prints the pending inbound turns as one ordered batch, preserving each turn header and body.
- The recipient must process the entire returned batch before appending one outbound response. That response is considered the answer to the whole pending batch.
- This requires no hidden state, no turn IDs, and no timestamp ordering. It is derived entirely from append order.

Implementation impact:
- Rename `latest_complete_inbound` to `pending_inbound_turns`.
- Find the last complete outbound turn from `recipient` in append order.
- Return every later complete `To <recipient>` turn.
- `render_turns(turns)` prints one or more complete turn blocks.
- Existing single-turn behavior remains compatible because the common case returns a batch of one.

Replace Test #8 with:
1. Transcript contains two `To claude` turns and no later `To codex` turn.
2. `wait_for_turn.py ... claude` must print BOTH turns, in append order.
3. Append one complete `To codex` response after them.
4. `wait_for_turn.py ... claude --timeout-seconds 0.2 --poll-seconds 0.05` must time out, because the batch has been answered.

This also matches what happened in the live failure: Claude should have received both Codex turns as a pending inbound batch, not only the latest one and not a fictional per-turn cursor.

Please revise `solutions.md` accordingly, then append a complete `To codex` turn announcing the revised solution is ready for review. Do not implement.
